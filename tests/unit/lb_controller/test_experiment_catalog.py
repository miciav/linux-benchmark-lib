import json
from pathlib import Path

import pytest

from lb_controller.api import RunCatalogService

pytestmark = pytest.mark.unit_controller


def _run(
    root: Path, run_id: str, created: str, experiment: str | None, host: str
) -> None:
    run_dir = root / run_id
    run_dir.mkdir(parents=True)
    metadata = {"created_at": created}
    if experiment is not None:
        metadata["experiment_id"] = experiment
    tasks = [{"host": host, "workload": "fio"}]
    (run_dir / "run_journal.json").write_text(
        json.dumps({"run_id": run_id, "metadata": metadata, "tasks": tasks})
    )


@pytest.fixture
def catalog(tmp_path: Path) -> RunCatalogService:
    root = tmp_path / "benchmark_results"
    _run(root, "run-a1", "2026-10-09T10:00:00", "tuning", "h1")
    _run(root, "run-a2", "2026-10-09T12:00:00", "tuning", "h2")
    _run(root, "run-b1", "2026-10-09T11:00:00", "other", "h1")
    _run(root, "run-old", "2026-10-01T09:00:00", None, "h1")  # before this change
    return RunCatalogService(root)


def test_runs_expose_their_experiment(catalog: RunCatalogService) -> None:
    run = catalog.get_run("run-a1")
    assert run is not None and run.experiment_id == "tuning"


def test_runs_group_by_experiment_newest_first(catalog: RunCatalogService) -> None:
    experiments = catalog.list_experiments()
    assert [e.id for e in experiments] == ["tuning", "other", "run-old"]
    tuning = experiments[0]
    assert tuning.kind == "experiment"
    assert [r.run_id for r in tuning.runs] == ["run-a1", "run-a2"]
    assert tuning.hosts == ["h1", "h2"]
    assert tuning.workloads == ["fio"]
    assert str(tuning.first_created) == "2026-10-09 10:00:00"
    assert str(tuning.last_created) == "2026-10-09 12:00:00"


def test_older_runs_stay_one_run_experiments(catalog: RunCatalogService) -> None:
    old = catalog.get_experiment("run-old")
    assert old is not None and [r.run_id for r in old.runs] == ["run-old"]


def test_get_experiment_unknown_is_none(catalog: RunCatalogService) -> None:
    assert catalog.get_experiment("nope") is None


def test_folder_experiment_holds_every_run(catalog: RunCatalogService) -> None:
    folder = catalog.folder_experiment()
    assert folder.kind == "folder"
    assert folder.id == "benchmark_results"
    assert len(folder.runs) == 4


def test_an_empty_folder_has_no_experiments(tmp_path: Path) -> None:
    empty = RunCatalogService(tmp_path / "nothing-here")
    assert empty.list_experiments() == []
    assert empty.folder_experiment().runs == []
