from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from lb_common.api import RunInfo
from lb_runner.api import BenchmarkConfig, WorkloadConfig


def _load_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("LB_ENABLE_TEST_CLI", "1")
    monkeypatch.delenv("LB_CONFIG_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    for mod in list(sys.modules.keys()):
        if mod.startswith(("lb_ui.cli", "lb_ui.api")):
            del sys.modules[mod]
    return importlib.import_module("lb_ui.api")


def _ensure_workload_enabled(cfg: BenchmarkConfig, name: str) -> None:
    if name not in cfg.workloads:
        cfg.workloads[name] = WorkloadConfig(plugin=name, options={})


@pytest.mark.unit_ui
def test_resume_cli_uses_app_api_for_run_catalog_service() -> None:
    module_path = Path("lb_ui/cli/commands/resume.py")
    tree = ast.parse(module_path.read_text(), filename=str(module_path))

    assert any(
        isinstance(node, ast.ImportFrom)
        and node.module == "lb_app.api"
        and any(alias.name == "RunCatalogService" for alias in node.names)
        for node in tree.body
    )
    assert not any(
        isinstance(node, ast.ImportFrom)
        and node.module == "lb_controller.api"
        and any(alias.name == "RunCatalogService" for alias in node.names)
        for node in tree.body
    )


@pytest.mark.unit_ui
def test_resume_uses_run_catalog_service(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cli = _load_cli(monkeypatch, tmp_path)
    runner = CliRunner()

    cfg = BenchmarkConfig()
    _ensure_workload_enabled(cfg, "stress_ng")
    cfg.output_dir = tmp_path / "benchmark_results"
    cfg_path = tmp_path / "cfg.json"
    cfg.save(cfg_path)

    from lb_app.api import RunJournal
    import lb_ui.cli.commands.resume as resume_mod

    run_id = "run-20250101-000000"
    journal = RunJournal.initialize(run_id, cfg, ["stress_ng"])
    journal.metadata["execution_mode"] = "remote"
    journal_path = cfg.output_dir / run_id / "run_journal.json"
    journal.save(journal_path)

    run_info = RunInfo(
        run_id=run_id,
        output_root=journal_path.parent,
        report_root=None,
        data_export_root=None,
        hosts=["host1"],
        workloads=["stress_ng"],
        created_at=None,
        journal_path=journal_path,
    )

    catalog_calls: list[Path] = []

    def fake_list_runs(self):
        catalog_calls.append(self.output_dir)
        return [run_info]

    monkeypatch.setattr(resume_mod.RunCatalogService, "list_runs", fake_list_runs)

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

    result = runner.invoke(cli.app, ["resume", run_id, "-c", str(cfg_path), "--remote"])

    assert result.exit_code == 0, result.output
    assert captured["request"].resume == run_id
    assert catalog_calls == [cfg.output_dir.resolve()]
