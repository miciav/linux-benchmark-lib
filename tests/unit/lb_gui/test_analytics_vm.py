"""Unit tests for AnalyticsViewModel (experiment unification)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from lb_app.api import RunCatalogService, UnificationService
from tests.helpers.analytics_runs import collected_run

pytest.importorskip("PySide6")

pytestmark = pytest.mark.unit


@pytest.fixture
def vm(tmp_path: Path):
    from lb_gui.viewmodels.analytics_vm import AnalyticsViewModel

    root = tmp_path / "benchmark_results"
    collected_run(root, "run-1", "tuning", "fio", "2026-10-09T10:00:00")
    collected_run(root, "run-2", "tuning", "stress_ng", "2026-10-09T11:00:00")
    catalog = MagicMock()
    catalog.unification.return_value = UnificationService(
        RunCatalogService(root), tmp_path / "exports"
    )
    model = AnalyticsViewModel(catalog)
    model.refresh_runs()
    return model


def test_the_folder_is_listed_first(vm):
    assert [(e.kind, e.id) for e in vm.experiments] == [
        ("folder", "benchmark_results"),
        ("experiment", "tuning"),
    ]
    assert vm.get_experiment_rows()[0][0] == "Folder benchmark_results (all runs)"


def test_selecting_defaults_the_filters_to_everything(vm):
    vm.select_experiment(1)
    assert vm.selected_experiment.id == "tuning"
    assert vm.selected_hosts == ["h1"]
    assert vm.selected_workloads == ["fio", "stress_ng"]
    assert vm.preview is None


def test_prepare_then_unify_writes(vm, tmp_path):
    completed: list[list[Path]] = []
    vm.analytics_completed.connect(completed.append)
    vm.select_experiment(1)
    vm.prepare()
    assert vm.preview is not None and vm.can_unify
    vm.unify()
    assert completed and (tmp_path / "exports" / "tuning" / "results.parquet").exists()


def test_changing_a_filter_drops_the_preview(vm):
    vm.select_experiment(1)
    vm.prepare()
    vm.selected_workloads = ["fio"]
    assert vm.preview is None
    assert not vm.can_unify


def test_an_empty_preview_cannot_be_unified(vm, tmp_path):
    failed: list[str] = []
    vm.analytics_failed.connect(failed.append)
    vm.select_experiment(1)
    vm.selected_hosts = ["nobody"]
    vm.prepare()
    assert vm.preview is not None and vm.preview.is_empty
    assert not vm.can_unify
    vm.unify()
    assert failed
    assert not (tmp_path / "exports").exists()


def test_prepare_without_selection_fails(vm):
    failed: list[str] = []
    vm.analytics_failed.connect(failed.append)
    vm.prepare()
    assert failed == ["No experiment selected"]
