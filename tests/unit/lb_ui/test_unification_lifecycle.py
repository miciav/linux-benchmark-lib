from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from lb_app.api import ConfigService
from lb_runner.api import BenchmarkConfig
from lb_ui.flows import unification
from lb_ui.tui.system.headless import HeadlessUI
from lb_ui.wiring.dependencies import UIContext
from tests.helpers.analytics_runs import collected_run

pytestmark = pytest.mark.unit_ui


class ScriptedPicker:
    def __init__(self, ones: Sequence[str]):
        self.ones = list(ones)

    def pick_one(self, items, *, title, query_hint=""):
        want = self.ones.pop(0)
        return next((item for item in items if item.id == want), None)

    def pick_many(self, items, *, title, query_hint=""):
        return []


@pytest.fixture
def cfg(tmp_path: Path) -> BenchmarkConfig:
    root = tmp_path / "benchmark_results"
    collected_run(root, "run-1", "tuning", "fio", "2026-10-09T10:00:00")
    collected_run(root, "run-2", "tuning", "stress_ng", "2026-10-09T11:00:00")
    return BenchmarkConfig(output_dir=root, data_export_dir=tmp_path / "exports")


def _ctx(headless: bool, confirm: bool = False) -> UIContext:
    ui = HeadlessUI()
    ui.next_confirm_response = confirm
    ctx = UIContext(headless=headless)
    ctx.ui = ui
    return ctx


def _journal(cfg: BenchmarkConfig) -> Path:
    return cfg.output_dir / "run-2" / "run_journal.json"


def test_forced_unifies_the_whole_experiment(cfg, tmp_path):
    assert unification.unify_after_run(
        _ctx(headless=True), cfg, _journal(cfg), None, forced=True
    )
    import pandas as pd

    runs = pd.read_parquet(tmp_path / "exports" / "tuning" / "runs.parquet")
    assert set(runs.run_id) == {"run-1", "run-2"}


def test_headless_without_analyze_does_nothing(cfg, tmp_path):
    assert unification.unify_after_run(
        _ctx(headless=True), cfg, _journal(cfg), None, forced=False
    )
    assert not (tmp_path / "exports").exists()


def test_the_prompt_defaults_to_no(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(unification, "is_tty_available", lambda: True)
    asked: list[bool] = []
    ctx = _ctx(headless=False)
    ctx.ui.form.confirm = lambda prompt, default=True: asked.append(default) or False
    unification.unify_after_run(ctx, cfg, _journal(cfg), None, forced=False)
    assert asked == [False]
    assert not (tmp_path / "exports").exists()


def test_yes_to_the_prompt_unifies(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(unification, "is_tty_available", lambda: True)
    ctx = _ctx(headless=False, confirm=True)
    assert unification.unify_after_run(ctx, cfg, _journal(cfg), None, forced=False)
    assert (tmp_path / "exports" / "tuning" / "results.parquet").exists()


def test_a_failed_forced_unification_reports_false(cfg, monkeypatch):
    monkeypatch.setattr(
        "lb_app.services.unification_service._has_pyarrow", lambda: False
    )
    ctx = _ctx(headless=True)
    assert not unification.unify_after_run(ctx, cfg, _journal(cfg), None, forced=True)
    assert any("pyarrow" in m for m in ctx.ui.recorded_messages)


def test_a_journal_without_experiment_warns_and_skips(cfg, tmp_path):
    journal = tmp_path / "old" / "run_journal.json"
    journal.parent.mkdir()
    journal.write_text('{"run_id": "old", "metadata": {}, "tasks": []}')
    ctx = _ctx(headless=True)
    assert unification.unify_after_run(ctx, cfg, journal, None, forced=True)
    assert any("no experiment id" in m for m in ctx.ui.recorded_messages)


def _load_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    import importlib
    import sys

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("LB_ENABLE_TEST_CLI", "1")
    monkeypatch.setenv("LB_SUPPRESS_SUMMARY", "1")
    monkeypatch.delenv("LB_CONFIG_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    for mod in list(sys.modules):
        if mod.startswith(("lb_ui.cli", "lb_ui.api")):
            del sys.modules[mod]
    return importlib.import_module("lb_ui.api")


@pytest.mark.parametrize(
    ("flag", "forced"), [([], False), (["--analyze"], True), (["--no-analyze"], None)]
)
def test_lb_run_hands_the_journal_to_the_end_of_run_step(
    cfg, tmp_path, monkeypatch, flag, forced
):
    import sys

    cli = _load_cli(monkeypatch, tmp_path)
    cfg.workloads["stress_ng"] = cfg.workloads.get("stress_ng") or __import__(
        "lb_runner.api", fromlist=["WorkloadConfig"]
    ).WorkloadConfig(plugin="stress_ng", options={})
    cfg_path = tmp_path / "cfg.json"
    cfg.save(cfg_path)
    monkeypatch.setattr(
        cli.app_client,
        "_provision",
        lambda config, execution_mode, node_count, docker_engine=None, resume=None: (
            config,
            None,
        ),
    )
    journal = _journal(cfg)
    monkeypatch.setattr(
        cli.app_client,
        "start_run",
        lambda *_a, **_k: SimpleNamespace(
            journal_path=journal, log_path=None, ui_log_path=None
        ),
    )
    calls: list[tuple[Path, bool]] = []
    run_module = sys.modules["lb_ui.cli.commands.run"]
    monkeypatch.setattr(
        run_module,
        "unify_after_run",
        lambda ctx, cfg, path, config_path, *, forced: (
            calls.append((path, forced)) or not forced
        ),
    )
    result = CliRunner().invoke(cli.app, ["run", "-c", str(cfg_path), *flag])
    if forced is None:  # --no-analyze: never ask, never unify
        assert calls == []
        assert result.exit_code == 0, result.output
        return
    assert calls == [(journal, forced)]
    # --analyze with a failed unification exits 1; the prompt path never does.
    assert result.exit_code == (1 if forced else 0), result.output


def test_runs_list_analyze_starts_the_flow_at_the_summary(cfg, tmp_path, monkeypatch):
    import lb_ui.api as cli
    from lb_ui.tui.core import capabilities

    monkeypatch.setattr(
        cli.ctx_store, "config_service", ConfigService(config_home=tmp_path / "c")
    )
    monkeypatch.setattr(capabilities, "is_tty_available", lambda: True)
    ui = HeadlessUI()
    ui.picker = ScriptedPicker(["run-1", "analyze", "unify"])  # type: ignore[assignment]
    monkeypatch.setattr(cli.ctx_store, "ui", ui)
    monkeypatch.setattr(cli.ctx_store, "headless", False)
    cfg_path = tmp_path / "cfg.json"
    cfg.save(cfg_path)
    result = CliRunner().invoke(cli.app, ["runs", "list", "-c", str(cfg_path)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "exports" / "tuning" / "results.parquet").exists()


def test_a_write_failure_after_yes_is_reported_not_raised(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(unification, "is_tty_available", lambda: True)
    (tmp_path / "exports").write_text("not a folder")
    ctx = _ctx(headless=False, confirm=True)
    assert not unification.unify_after_run(ctx, cfg, _journal(cfg), None, forced=False)
    assert any("Could not write" in m for m in ctx.ui.recorded_messages)


def test_analyze_without_a_journal_warns(cfg, tmp_path, monkeypatch):
    cli = _load_cli(monkeypatch, tmp_path)
    from lb_runner.api import WorkloadConfig

    cfg.workloads["stress_ng"] = WorkloadConfig(plugin="stress_ng", options={})
    cfg_path = tmp_path / "cfg.json"
    cfg.save(cfg_path)
    monkeypatch.setattr(
        cli.app_client,
        "_provision",
        lambda config, execution_mode, node_count, docker_engine=None, resume=None: (
            config,
            None,
        ),
    )
    monkeypatch.setattr(
        cli.app_client,
        "start_run",
        lambda *_a, **_k: SimpleNamespace(
            journal_path=None, log_path=None, ui_log_path=None
        ),
    )
    result = CliRunner().invoke(cli.app, ["run", "-c", str(cfg_path), "--analyze"])
    assert "no run journal" in " ".join(result.output.split())
