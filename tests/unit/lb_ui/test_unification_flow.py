from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from lb_app.api import RunCatalogService, UnificationService
from lb_ui.flows.unification import run_unification_flow
from lb_ui.tui.system.headless import HeadlessUI
from lb_ui.wiring.dependencies import UIContext
from tests.helpers.analytics_runs import collected_run

pytestmark = pytest.mark.unit_ui


class ScriptedPicker:
    """Answers pick_one/pick_many from scripted item ids, in order."""

    def __init__(self, ones: Sequence[str | None], manys: Sequence[list[str]] = ()):
        self.ones = list(ones)
        self.manys = list(manys)
        self.seen: list[list[str]] = []

    def pick_one(self, items, *, title, query_hint=""):
        self.seen.append([item.id for item in items])
        want = self.ones.pop(0)
        return next((item for item in items if item.id == want), None)

    def pick_many(self, items, *, title, query_hint=""):
        want = self.manys.pop(0)
        return [item for item in items if item.id in want]


def _ctx(picker: ScriptedPicker) -> tuple[UIContext, HeadlessUI]:
    ui = HeadlessUI()
    ui.picker = picker  # type: ignore[assignment]
    ctx = UIContext(headless=True)
    ctx.ui = ui
    return ctx, ui


@pytest.fixture
def service(tmp_path: Path) -> UnificationService:
    root = tmp_path / "tuning"  # a folder named like the experiment it holds
    collected_run(root, "run-1", "tuning", "fio", "2026-10-09T10:00:00")
    collected_run(root, "run-2", "tuning", "stress_ng", "2026-10-09T11:00:00")
    return UnificationService(RunCatalogService(root), tmp_path / "exports")


def test_pick_review_unify(service, tmp_path):
    picker = ScriptedPicker(["experiment:tuning", "unify"])
    ctx, ui = _ctx(picker)
    paths = run_unification_flow(ctx, service)
    assert paths
    assert picker.seen[0] == ["experiment:tuning", "folder:tuning"]
    assert (tmp_path / "exports" / "tuning" / "results.parquet").exists()
    titles = [t.model.title for t in ui.recorded_tables]
    assert titles[0] == "Unification of tuning"
    assert any("Equivalent command: lb runs analyze" in m for m in ui.recorded_messages)


def test_the_folder_entry_unifies_every_run(service, tmp_path):
    ctx, _ = _ctx(ScriptedPicker(["folder:tuning", "unify"]))
    run_unification_flow(ctx, service)
    folder_out = tmp_path / "exports" / "_folders" / "tuning"
    runs = pd.read_parquet(folder_out / "runs.parquet")
    assert set(runs.run_id) == {"run-1", "run-2"}


def test_filters_then_unify(service, tmp_path):
    picker = ScriptedPicker(
        ["experiment:tuning", "filters", "unify"], manys=[["h1"], ["fio"]]
    )
    ctx, _ = _ctx(picker)
    run_unification_flow(ctx, service)
    results = pd.read_parquet(tmp_path / "exports" / "tuning" / "results.parquet")
    assert set(results.workload) == {"fio"}


def test_deselecting_everything_keeps_the_previous_filter(service, tmp_path):
    picker = ScriptedPicker(
        ["experiment:tuning", "filters", "filters", "unify"],
        manys=[["h1"], ["fio"], [], []],
    )
    ctx, _ = _ctx(picker)
    run_unification_flow(ctx, service)
    results = pd.read_parquet(tmp_path / "exports" / "tuning" / "results.parquet")
    assert set(results.workload) == {"fio"}


def test_cancel_writes_nothing(service, tmp_path):
    ctx, _ = _ctx(ScriptedPicker(["experiment:tuning", "cancel"]))
    assert run_unification_flow(ctx, service) is None
    assert not (tmp_path / "exports").exists()


def test_a_preselected_experiment_starts_at_the_summary(service, tmp_path):
    picker = ScriptedPicker(["unify"])
    ctx, _ = _ctx(picker)
    run_unification_flow(ctx, service, service.find("tuning"))
    assert picker.seen == [["unify", "filters", "cancel"]]


def test_an_empty_preview_offers_no_unify(service, monkeypatch):
    real_prepare = service.prepare
    monkeypatch.setattr(
        service,
        "prepare",
        lambda experiment, hosts=(), workloads=(): (
            preview := real_prepare(experiment, hosts, workloads),
            replace(preview, data=preview.data.filter(hosts=["nobody"])),
        )[1],
    )
    picker = ScriptedPicker(["cancel"])
    ctx, _ = _ctx(picker)
    run_unification_flow(ctx, service, service.find("tuning"))
    assert picker.seen == [["filters", "cancel"]]
