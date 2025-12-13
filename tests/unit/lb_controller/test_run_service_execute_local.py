"""RunService.execute local path tests (mocked)."""

from pathlib import Path

import pytest

from lb_controller.services.run_service import RunService
from lb_runner.benchmark_config import BenchmarkConfig, WorkloadConfig


pytestmark = pytest.mark.unit


class DummyGenerator:
    """Minimal generator used when LocalRunner is not patched."""

    _is_running = False

    def prepare(self):
        return None

    def start(self):
        return None

    def stop(self):
        return None

    def get_result(self):
        return {"returncode": 0}


class DummyPlugin:
    def export_results_to_csv(self, *args, **kwargs):
        return []


class DummyRegistry:
    """Registry stub to keep LocalRunner happy even if monkeypatch misses."""

    def get(self, name: str):
        return DummyPlugin()

    def create_generator(self, name: str, cfg):
        return DummyGenerator()

    def create_collectors(self, cfg):
        return []


def test_execute_local_updates_journal(tmp_path: Path):
    cfg = BenchmarkConfig()
    cfg.workloads = {"stress_ng": WorkloadConfig(plugin="stress_ng", enabled=True)}
    cfg.repetitions = 1
    cfg.warmup_seconds = 0
    cfg.cooldown_seconds = 0
    cfg.collect_system_info = False
    cfg.output_dir = tmp_path / "out"
    cfg.report_dir = tmp_path / "rep"
    cfg.data_export_dir = tmp_path / "exp"
    cfg.remote_execution.run_setup = False
    cfg.remote_execution.run_teardown = False
    svc = RunService(registry_factory=lambda: DummyRegistry())
    ctx = svc.build_context(cfg, tests=["stress_ng"], remote_override=False)

    result = svc.execute(ctx, run_id="run-1", ui_adapter=None)

    assert result.journal_path and result.journal_path.exists()
    journal = result.journal_path
    from lb_controller.journal import RunJournal, RunStatus

    saved = RunJournal.load(journal)
    task = saved.get_task("localhost", "stress_ng", 1)
    assert task is not None
    assert task.status in (RunStatus.PENDING, RunStatus.COMPLETED)
