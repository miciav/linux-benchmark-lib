"""RunService.execute container path tests (mocked)."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from lb_controller.services.run_service import RunService
from lb_runner.benchmark_config import BenchmarkConfig, WorkloadConfig

pytestmark = pytest.mark.unit


class DummyContainerRunner:
    def __init__(self):
        self.calls = []

    def run_workload(
        self,
        spec,
        test_name,
        plugin,
        ui_adapter=None,
        output_callback=None,
        stop_token=None,
    ):
        self.calls.append((spec, test_name, plugin))
        if output_callback:
            output_callback("LB_EVENT {\"run_id\":\"run-1\",\"host\":\"localhost\",\"workload\":\"stress_ng\",\"repetition\":1,\"total_repetitions\":1,\"status\":\"done\"}", end="\n")


def test_execute_container_updates_journal(monkeypatch, tmp_path):
    cfg = BenchmarkConfig()
    cfg.workloads = {"stress_ng": WorkloadConfig(plugin="stress_ng", enabled=True)}
    cfg.output_dir = tmp_path / "out"
    cfg.report_dir = tmp_path / "rep"
    cfg.data_export_dir = tmp_path / "exp"
    cfg.remote_execution.run_setup = False
    cfg.remote_execution.run_teardown = False

    dummy_runner = DummyContainerRunner()
    monkeypatch.setattr("lb_controller.services.run_service.ContainerRunner", lambda: dummy_runner)
    registry = MagicMock()
    registry.get.return_value = MagicMock(name="Plugin")
    svc = RunService(registry_factory=lambda: registry)
    svc._container_runner = dummy_runner  # use the stub directly
    ctx = svc.build_context(cfg, tests=["stress_ng"], remote_override=False, docker=True)

    result = svc.execute(ctx, run_id="run-1", ui_adapter=None)

    assert result.journal_path and result.journal_path.exists()
    from lb_controller.journal import RunJournal, RunStatus

    saved = RunJournal.load(result.journal_path)
    task = saved.get_task("localhost", "stress_ng", 1)
    assert task is not None
    assert task.status in (RunStatus.RUNNING, RunStatus.COMPLETED, RunStatus.FAILED)
    assert dummy_runner.calls, "Container runner should be invoked"
