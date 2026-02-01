"""Unit tests for runner progress events."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from lb_runner.api import BenchmarkConfig, LocalRunner, WorkloadConfig


pytestmark = pytest.mark.unit_runner


def _make_runner() -> LocalRunner:
    cfg = BenchmarkConfig(
        output_dir=Path("/tmp/out"),
        report_dir=Path("/tmp/report"),
        data_export_dir=Path("/tmp/export"),
        workloads={"dummy": WorkloadConfig(plugin="stress_ng")},
        warmup_seconds=0,
        cooldown_seconds=0,
    )
    return LocalRunner(cfg, registry=MagicMock())


def test_run_single_repetition_emits_done() -> None:
    runner = _make_runner()
    runner._planner = MagicMock()
    runner._planner.resolve_config_input.return_value = {}
    runner._emit_progress = MagicMock()

    workload_cfg = WorkloadConfig(plugin="stress_ng")

    # Mock RepetitionExecutor.run_attempt
    with patch("lb_runner.engine.runner.RepetitionExecutor") as MockExecutor:
        executor_instance = MockExecutor.return_value
        executor_instance.run_attempt.return_value = SimpleNamespace(
            success=True,
            status="done",
            result={"success": True},
            message="",
            error_type=None,
            error_context=None,
        )

        result = runner._run_single_repetition(
            "dummy",
            workload_cfg,
            MagicMock(),
            repetition=1,
            total_reps=1,
        )

    assert result is True
    runner._emit_progress.assert_any_call("dummy", 1, 1, "running")
    runner._emit_progress.assert_any_call(
        "dummy",
        1,
        1,
        "done",
        message="",
        error_type=None,
        error_context=None,
    )


def test_run_single_repetition_emits_failed() -> None:
    runner = _make_runner()
    runner._planner = MagicMock()
    runner._planner.resolve_config_input.return_value = {}
    runner._emit_progress = MagicMock()

    workload_cfg = WorkloadConfig(plugin="stress_ng")

    # Mock RepetitionExecutor.run_attempt
    with patch("lb_runner.engine.runner.RepetitionExecutor") as MockExecutor:
        executor_instance = MockExecutor.return_value
        executor_instance.run_attempt.return_value = SimpleNamespace(
            success=False,
            status="failed",
            result={"success": False},
            message="",
            error_type=None,
            error_context=None,
        )

        result = runner._run_single_repetition(
            "dummy",
            workload_cfg,
            MagicMock(),
            repetition=1,
            total_reps=1,
        )

    assert result is False
    runner._emit_progress.assert_any_call("dummy", 1, 1, "running")
    runner._emit_progress.assert_any_call(
        "dummy",
        1,
        1,
        "failed",
        message="",
        error_type=None,
        error_context=None,
    )
