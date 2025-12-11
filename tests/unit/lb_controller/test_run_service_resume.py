"""Tests for RunService resume/partial failure handling."""

from pathlib import Path

import pytest

from lb_controller.journal import RunJournal, RunStatus
from lb_controller.services.run_service import RunService
from lb_runner.benchmark_config import BenchmarkConfig, WorkloadConfig


pytestmark = pytest.mark.unit


def _seed_journal(tmp_path: Path) -> tuple[RunJournal, Path]:
    cfg = BenchmarkConfig()
    cfg.workloads = {"stress_ng": WorkloadConfig(plugin="stress_ng", enabled=True)}
    journal = RunJournal.initialize("run-1", cfg, ["stress_ng"])
    # Mark rep 1 completed
    journal.update_task("localhost", "stress_ng", 1, RunStatus.COMPLETED)
    journal_path = tmp_path / "run_journal.json"
    journal.save(journal_path)
    return journal, journal_path


def test_execute_resume_skips_completed(monkeypatch, tmp_path):
    journal, journal_path = _seed_journal(tmp_path)
    cfg = journal.metadata.get("config") or BenchmarkConfig()
    cfg.output_dir = tmp_path / "out"
    cfg.report_dir = tmp_path / "rep"
    cfg.data_export_dir = tmp_path / "exp"
    cfg.remote_execution.run_setup = False
    cfg.remote_execution.run_teardown = False

    class DummyRunner:
        def __init__(self, *args, **kwargs):
            self.calls = []

        def run_benchmark(self, test_name, run_id=None):
            self.calls.append(test_name)
            return True

    dummy = DummyRunner()
    monkeypatch.setattr("lb_controller.services.run_service.LocalRunner", lambda *a, **k: dummy)
    svc = RunService(registry_factory=lambda: None)
    ctx = svc.build_context(cfg, tests=["stress_ng"], remote_override=False)
    ctx.resume_from = "run-1"
    ctx.resume_latest = False

    # Place the journal in the expected path
    target_path = cfg.output_dir / "run-1" / "run_journal.json"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    journal.save(target_path)

    result = svc.execute(ctx, run_id=None, ui_adapter=None)
    assert result.journal_path and result.journal_path.exists()
    saved = RunJournal.load(result.journal_path)
    # Rep 1 stays completed, rep 2 may remain pending/completed depending on dummy run
    rep1 = saved.get_task("localhost", "stress_ng", 1)
    rep2 = saved.get_task("localhost", "stress_ng", 2)
    assert rep1 and rep1.status == RunStatus.COMPLETED
    assert rep2 is not None
