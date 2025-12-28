import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from lb_runner.api import BenchmarkConfig, WorkloadConfig


pytestmark = pytest.mark.inter_generic


def _load_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Import the CLI module with an isolated config home and cwd."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("LB_ENABLE_TEST_CLI", "1")
    monkeypatch.chdir(tmp_path)
    for mod in list(sys.modules.keys()):
        if mod.startswith(("lb_ui.cli", "lb_ui.api")):
            del sys.modules[mod]
    return importlib.import_module("lb_ui.api")


def _ensure_workload_enabled(cfg: BenchmarkConfig, name: str) -> None:
    if name not in cfg.workloads:
        cfg.workloads[name] = WorkloadConfig(plugin=name, enabled=True)
        return
    cfg.workloads[name].enabled = True


def test_resume_command_uses_journal_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    cli = _load_cli(monkeypatch, tmp_path)
    runner = CliRunner()

    cfg = BenchmarkConfig()
    _ensure_workload_enabled(cfg, "stress_ng")
    cfg.output_dir = tmp_path / "benchmark_results"
    cfg_path = tmp_path / "cfg.json"
    cfg.save(cfg_path)

    from lb_app.api import RunJournal

    run_id = "run-20250101-000000"
    journal = RunJournal.initialize(run_id, cfg, ["stress_ng"])
    journal.metadata["execution_mode"] = "docker"
    journal.metadata["node_count"] = 2
    journal_path = cfg.output_dir / run_id / "run_journal.json"
    journal.save(journal_path)

    captured = {}

    def fake_start_run(request, hooks):
        captured["request"] = request
        return SimpleNamespace(
            summary=None,
            journal_path=None,
            log_path=None,
            ui_log_path=None,
        )

    monkeypatch.setattr(cli.app_client, "start_run", fake_start_run)
    monkeypatch.setattr(cli.app_client, "get_run_plan", lambda *args, **kwargs: [])

    result = runner.invoke(cli.app, ["resume", run_id, "-c", str(cfg_path)])

    assert result.exit_code == 0, result.output
    request = captured["request"]
    assert request.resume == run_id
    assert request.execution_mode == "docker"
    assert request.node_count == 2
