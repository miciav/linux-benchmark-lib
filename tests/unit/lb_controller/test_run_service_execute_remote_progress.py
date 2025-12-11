"""Remote execute progress parsing tests with mocked output."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from lb_controller.services.run_service import RunService
from lb_runner.benchmark_config import BenchmarkConfig, WorkloadConfig


pytestmark = pytest.mark.unit


def test_remote_progress_lines_update_journal(monkeypatch, tmp_path):
    cfg = BenchmarkConfig()
    cfg.workloads = {"stress_ng": WorkloadConfig(plugin="stress_ng", enabled=True)}
    cfg.output_dir = tmp_path / "out"
    cfg.report_dir = tmp_path / "rep"
    cfg.data_export_dir = tmp_path / "exp"
    cfg.remote_execution.enabled = True
    cfg.remote_execution.run_setup = False
    cfg.remote_execution.run_teardown = False
    cfg.remote_hosts = [SimpleNamespace(name="h1")]

    class DummyController:
        def __init__(self, *args, output_callback=None, **kwargs):
            self._cb = output_callback

        def run(self, *args, **kwargs):
            # Simulate emitting progress lines through output callback
            cb = kwargs.get("output_callback") or self._cb
            if cb:
                cb('LB_EVENT {"run_id":"run-1","host":"h1","workload":"stress_ng","repetition":1,"total_repetitions":1,"status":"running"}', end="\n")
                cb('LB_EVENT {"run_id":"run-1","host":"h1","workload":"stress_ng","repetition":1,"total_repetitions":1,"status":"done"}', end="\n")
            return MagicMock()

    monkeypatch.setattr("lb_controller.controller.BenchmarkController", DummyController)
    svc = RunService(registry_factory=lambda: MagicMock())
    ctx = svc.build_context(cfg, tests=["stress_ng"], remote_override=True)

    result = svc.execute(ctx, run_id="run-1", ui_adapter=None)
    from lb_controller.journal import RunJournal, RunStatus

    journal = RunJournal.load(result.journal_path)
    task = journal.get_task("h1", "stress_ng", 1)
    assert task is not None
    assert task.status == RunStatus.COMPLETED
