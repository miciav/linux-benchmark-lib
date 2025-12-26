"""Runner edge-case tests."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from lb_runner.api import BenchmarkConfig, WorkloadConfig
from lb_runner.api import LocalRunner


pytestmark = pytest.mark.unit_runner


def test_collector_start_failure_does_not_crash(mocker, tmp_path):
    cfg = BenchmarkConfig(
        output_dir=tmp_path / "out",
        report_dir=tmp_path / "rep",
        data_export_dir=tmp_path / "exp",
        workloads={"dummy": WorkloadConfig(plugin="stress_ng", enabled=True)},
        warmup_seconds=0,
        cooldown_seconds=0,
    )
    registry = MagicMock()
    bad_collector = MagicMock()
    bad_collector.name = "BadCollector"
    bad_collector.start.side_effect = RuntimeError("boom")
    bad_collector.get_data.return_value = []
    good_collector = MagicMock()
    good_collector.name = "GoodCollector"
    good_collector.get_data.return_value = []
    registry.create_collectors.return_value = [bad_collector, good_collector]
    registry.create_generator.return_value = MagicMock(_is_running=False, stop=lambda: None, get_result=lambda: {})
    runner = LocalRunner(cfg, registry=registry)

    runner.run_benchmark("dummy", total_repetitions=1)

    assert bad_collector.start.called
    assert good_collector.start.called


def test_system_info_write_failure_is_ignored(mocker, tmp_path):
    cfg = BenchmarkConfig(
        output_dir=tmp_path / "out",
        report_dir=tmp_path / "rep",
        data_export_dir=tmp_path / "exp",
        workloads={"dummy": WorkloadConfig(plugin="stress_ng", enabled=True)},
        warmup_seconds=0,
        cooldown_seconds=0,
        collect_system_info=True,
    )
    registry = MagicMock()
    registry.create_collectors.return_value = []
    mocker.patch("lb_runner.api.system_info_module.collect_system_info").return_value = MagicMock(to_dict=lambda: {})
    mocker.patch("lb_runner.api.storage_module.write_system_info_artifacts", side_effect=RuntimeError("fail"))
    registry.create_generator.return_value = MagicMock(_is_running=False, stop=lambda: None, get_result=lambda: {})

    runner = LocalRunner(cfg, registry=registry)
    runner.run_benchmark("dummy", total_repetitions=1)

    assert runner.system_info is not None


def test_mock_generator_without_flag_exits_promptly(monkeypatch, tmp_path):
    """Ensure MagicMock generators do not force long waits when _is_running is non-bool."""
    cfg = BenchmarkConfig(
        output_dir=tmp_path / "out",
        report_dir=tmp_path / "rep",
        data_export_dir=tmp_path / "exp",
        workloads={"dummy": WorkloadConfig(plugin="stress_ng", enabled=True)},
        warmup_seconds=0,
        cooldown_seconds=0,
        test_duration_seconds=300,  # would be long if loop didn't exit early
    )

    sleep_calls: list[int] = []

    def fake_sleep(seconds: int) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr("lb_runner.engine.execution.time.sleep", fake_sleep)
    monkeypatch.setattr("lb_runner.engine.runner.time.sleep", fake_sleep)

    generator = MagicMock()
    generator.get_result.return_value = {"returncode": 0}
    collectors: list[Any] = []

    class DummyRegistry:
        def get(self, name: str):
            return MagicMock()

        def create_generator(self, name: str, cfg: Any):
            return generator

        def create_collectors(self, cfg: BenchmarkConfig):
            return collectors

    runner = LocalRunner(cfg, registry=DummyRegistry())
    runner.run_benchmark("dummy", total_repetitions=1)

    # Without the guard, we'd accumulate ~310 sleep calls; ensure we skipped the loop.
    assert not sleep_calls
