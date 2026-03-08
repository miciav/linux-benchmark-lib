"""Tests for interruptible warmup/cooldown paths."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import lb_runner.engine.execution as execution_module
import lb_runner.engine.runner as runner_module
from lb_runner.api import BenchmarkConfig, LocalRunner, WorkloadConfig
from lb_runner.engine.execution import StopRequested, prepare_generator
from lb_runner.engine.stop_token import StopToken


pytestmark = [pytest.mark.unit, pytest.mark.unit_runner]


def test_prepare_generator_interrupts_warmup_without_monolithic_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generator = MagicMock()
    logger = MagicMock()
    stop_token = StopToken(enable_signals=False)
    sleep_calls: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        stop_token.request_stop()

    monkeypatch.setattr(execution_module.time, "sleep", fake_sleep)

    with pytest.raises(StopRequested):
        prepare_generator(
            generator,
            warmup_seconds=2,
            logger=logger,
            stop_token=stop_token,
        )

    generator.prepare.assert_called_once()
    assert sleep_calls
    assert max(sleep_calls) < 2


def test_run_benchmark_uses_interruptible_cooldown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfg = BenchmarkConfig(
        output_dir=tmp_path / "out",
        report_dir=tmp_path / "rep",
        data_export_dir=tmp_path / "exp",
        repetitions=2,
        cooldown_seconds=5,
        warmup_seconds=0,
        collect_system_info=False,
        workloads={"dummy": WorkloadConfig(plugin="stress_ng")},
    )
    stop_token = StopToken(enable_signals=False)
    registry = MagicMock()
    plugin = MagicMock()
    registry.get.return_value = plugin

    runner = LocalRunner(cfg, registry=registry, stop_token=stop_token)
    runner._planner.select_repetitions = MagicMock(return_value=[1, 2])
    runner._planner.resolve_workload = MagicMock(
        return_value=WorkloadConfig(plugin="stress_ng")
    )
    runner._prepare_run_scope = MagicMock()
    runner._run_single_repetition = MagicMock(return_value=True)

    cooldown_calls: list[tuple[float, StopToken]] = []

    def fake_sleep_with_stop_checks(
        total_seconds: float,
        token: StopToken | None,
        *,
        interval_seconds: float = 0.1,
    ) -> bool:
        assert interval_seconds == 0.1
        assert token is stop_token
        cooldown_calls.append((total_seconds, token))
        stop_token.request_stop()
        return False

    monkeypatch.setattr(
        runner_module,
        "sleep_with_stop_checks",
        fake_sleep_with_stop_checks,
        raising=False,
    )

    result = runner.run_benchmark("dummy", run_id="run-1")

    assert result is True
    assert runner._run_single_repetition.call_count == 1
    assert cooldown_calls == [(5, stop_token)]
