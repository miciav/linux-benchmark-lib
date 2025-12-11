"""RunService.execute local path tests (mocked)."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from lb_controller.services.run_service import RunService
from lb_runner.benchmark_config import BenchmarkConfig, WorkloadConfig
from lb_runner.events import RunEvent


pytestmark = pytest.mark.unit


class DummyLocalRunner:
    def __init__(self, *args, **kwargs):
        self.called = []

    def run_benchmark(self, test_name, run_id=None):
        self.called.append((test_name, run_id))
        return True


class DummyGenerator:
    """Minimal generator used when LocalRunner is not patched."""

    _is_running = False

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


def test_execute_local_updates_journal(monkeypatch, tmp_path):
    cfg = BenchmarkConfig()
    cfg.workloads = {"stress_ng": WorkloadConfig(plugin="stress_ng", enabled=True)}
    cfg.output_dir = tmp_path / "out"
    cfg.report_dir = tmp_path / "rep"
    cfg.data_export_dir = tmp_path / "exp"
    cfg.remote_execution.run_setup = False
    cfg.remote_execution.run_teardown = False

    dummy_runner = DummyLocalRunner()
    # Patch both the module attribute and the imported symbol to avoid regressions on refactors.
    import lb_controller.services.run_service as run_service_module

    monkeypatch.setattr(run_service_module, "LocalRunner", lambda *args, **kwargs: dummy_runner)
    monkeypatch.setattr("lb_controller.services.run_service.LocalRunner", lambda *args, **kwargs: dummy_runner)
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
    assert dummy_runner.called
