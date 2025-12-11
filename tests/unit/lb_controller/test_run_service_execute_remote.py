"""RunService.execute remote path tests (mocked)."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from lb_controller.services.run_service import RunService
from lb_runner.benchmark_config import BenchmarkConfig, WorkloadConfig

pytestmark = pytest.mark.unit


class DummyBenchmarkController:
    def __init__(self, *args, **kwargs):
        self.calls = []

    def run(self, tests, run_id=None, journal=None, resume=False, journal_path=None):
        self.calls.append((tests, run_id))
        return MagicMock()


def test_execute_remote_invokes_controller(monkeypatch, tmp_path):
    cfg = BenchmarkConfig()
    cfg.workloads = {"stress_ng": WorkloadConfig(plugin="stress_ng", enabled=True)}
    cfg.output_dir = tmp_path / "out"
    cfg.report_dir = tmp_path / "rep"
    cfg.data_export_dir = tmp_path / "exp"
    cfg.remote_execution.enabled = True
    cfg.remote_execution.run_setup = False
    cfg.remote_execution.run_teardown = False

    monkeypatch.setattr("lb_controller.controller.BenchmarkController", DummyBenchmarkController)
    registry = MagicMock()
    svc = RunService(registry_factory=lambda: registry)
    ctx = svc.build_context(cfg, tests=["stress_ng"], remote_override=True)

    result = svc.execute(ctx, run_id="run-remote", ui_adapter=None)

    assert result.journal_path and result.journal_path.exists()
    assert isinstance(result.summary, MagicMock) or result.summary is None
    from lb_controller.journal import RunJournal

    journal = RunJournal.load(result.journal_path)
    assert journal.run_id == "run-remote"
