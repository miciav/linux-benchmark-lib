"""Runner edge-case tests."""

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from lb_runner.api import BenchmarkConfig, LocalRunner, WorkloadConfig

pytestmark = pytest.mark.unit_runner


def test_collector_start_failure_does_not_crash(mocker, tmp_path):
    cfg = BenchmarkConfig(
        output_dir=tmp_path / "out",
        report_dir=tmp_path / "rep",
        data_export_dir=tmp_path / "exp",
        workloads={"dummy": WorkloadConfig(plugin="stress_ng")},
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
    registry.create_generator.return_value = MagicMock(
        _is_running=False, stop=lambda: None, get_result=lambda: {}
    )
    runner = LocalRunner(cfg, registry=registry)

    runner.run_benchmark("dummy", total_repetitions=1)

    assert bad_collector.start.called
    assert good_collector.start.called


def test_system_info_write_failure_is_ignored(mocker, tmp_path):
    cfg = BenchmarkConfig(
        output_dir=tmp_path / "out",
        report_dir=tmp_path / "rep",
        data_export_dir=tmp_path / "exp",
        workloads={"dummy": WorkloadConfig(plugin="stress_ng")},
        warmup_seconds=0,
        cooldown_seconds=0,
        collect_system_info=True,
    )
    registry = MagicMock()
    registry.create_collectors.return_value = []
    # Patch where MetricManager imports system_info
    mocker.patch(
        "lb_runner.engine.metrics.system_info.collect_system_info"
    ).return_value = MagicMock(to_dict=lambda: {})
    mocker.patch(
        "lb_runner.services.runner_output_manager.write_system_info_artifacts",
        side_effect=RuntimeError("fail"),
    )
    registry.create_generator.return_value = MagicMock(
        _is_running=False, stop=lambda: None, get_result=lambda: {}
    )

    runner = LocalRunner(cfg, registry=registry)
    runner.run_benchmark("dummy", total_repetitions=1)

    assert runner.system_info is not None


def test_mock_generator_without_flag_exits_promptly(monkeypatch, tmp_path):
    """Ensure MagicMock generators do not force long waits when _is_running is non-bool."""  # noqa: E501
    cfg = BenchmarkConfig(
        output_dir=tmp_path / "out",
        report_dir=tmp_path / "rep",
        data_export_dir=tmp_path / "exp",
        workloads={"dummy": WorkloadConfig(plugin="stress_ng")},
        warmup_seconds=0,
        cooldown_seconds=0,
        test_duration_seconds=300,  # would be long if loop didn't exit early
        # System-info collection shells out via subprocess, and CPython's
        # Popen._wait polls a running child with time.sleep(0.001), doubling on
        # each retry. Those calls land in the patched time.sleep below and made
        # this test flaky. This test is about the generator wait loop, so keep
        # the subprocess noise out of it.
        collect_system_info=False,
    )

    sleep_calls: list[int] = []

    def fake_sleep(seconds: int) -> None:
        sleep_calls.append(seconds)

    # sleep_with_stop_checks lives in lb_runner.engine.execution, so that is the
    # module whose `time.sleep` the runner actually calls. A second patch on
    # lb_runner.engine.runner.time was vestigial: that module no longer imports
    # `time` (it delegates sleeping), so patching it either did nothing or, once
    # the unused import was removed, raised ImportError.
    monkeypatch.setattr("lb_runner.engine.execution.time.sleep", fake_sleep)

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

    # The wait loop in wait_for_generator sleeps one second per iteration, so an
    # unguarded run would accumulate test_duration_seconds + safety_buffer
    # (~310) one-second sleeps. Asserting "no sleep at all" also caught
    # subprocess's own sub-millisecond polling and made this test flaky, so the
    # assertion is scoped to the durations the runner actually requests.
    assert not [s for s in sleep_calls if s >= 1]


def test_runner_records_error_type_on_failure(tmp_path):
    cfg = BenchmarkConfig(
        output_dir=tmp_path / "out",
        report_dir=tmp_path / "rep",
        data_export_dir=tmp_path / "exp",
        workloads={"dummy": WorkloadConfig(plugin="stress_ng")},
        warmup_seconds=0,
        cooldown_seconds=0,
    )
    plugin = MagicMock()
    plugin.name = "stress_ng"
    plugin.export_results_to_csv.return_value = []
    registry = MagicMock()
    registry.get.return_value = plugin
    registry.create_collectors.return_value = []

    generator = MagicMock()
    generator.start.side_effect = RuntimeError("boom")
    generator.get_result.return_value = {}
    generator._is_running = False
    registry.create_generator.return_value = generator

    runner = LocalRunner(cfg, registry=registry)
    success = runner.run_benchmark("dummy", total_repetitions=1, run_id="run-err")

    assert success is False
    result_path = cfg.output_dir / "run-err" / "dummy" / "rep1" / "result.json"
    payload = json.loads(result_path.read_text())
    assert payload["error_type"] == "WorkloadError"
    assert payload["success"] is False
