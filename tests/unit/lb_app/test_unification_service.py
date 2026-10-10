from pathlib import Path

import pandas as pd
import pytest

from lb_app.api import RunCatalogService, UnificationError, UnificationService
from lb_app.services import unification_service
from tests.helpers.analytics_runs import collected_run

pytestmark = pytest.mark.unit_analytics


@pytest.fixture
def root(tmp_path: Path) -> Path:
    root = tmp_path / "benchmark_results"
    collected_run(root, "run-1", "tuning", "fio", "2026-10-09T10:00:00")
    collected_run(root, "run-2", "tuning", "stress_ng", "2026-10-09T11:00:00")
    collected_run(root, "run-3", "other", "dd", "2026-10-09T09:00:00")
    return root


def _service(root: Path, tmp_path: Path, config: Path | None = None):
    return UnificationService(
        RunCatalogService(root), tmp_path / "exports", config_path=config
    )


def test_targets_are_experiments_newest_first_then_the_folder(root, tmp_path):
    targets = _service(root, tmp_path).list_targets()
    assert [(t.kind, t.id) for t in targets] == [
        ("experiment", "tuning"),
        ("experiment", "other"),
        ("folder", "benchmark_results"),
    ]


def test_an_empty_folder_has_no_targets_and_find_explains(tmp_path):
    service = _service(tmp_path / "missing", tmp_path)
    assert service.list_targets() == []
    with pytest.raises(UnificationError, match="No runs in"):
        service.find(None)


def test_find_names_recent_experiments_for_an_unknown_id(root, tmp_path):
    with pytest.raises(UnificationError, match=r"'nope' not found.*tuning, other"):
        _service(root, tmp_path).find("nope")


def test_find_none_is_the_folder(root, tmp_path):
    folder = _service(root, tmp_path).find(None)
    assert folder.kind == "folder"
    assert len(folder.runs) == 3


def test_prepare_loads_the_experiment_and_writes_it(root, tmp_path):
    service = _service(root, tmp_path)
    preview = service.prepare(service.find("tuning"))
    assert preview.out_dir == tmp_path / "exports" / "tuning"
    assert preview.row_counts["runs"] == 2
    assert not preview.is_empty
    paths = service.write(preview)
    assert {p.name for p in paths} >= {"results.parquet", "load_report.json"}
    results = pd.read_parquet(tmp_path / "exports" / "tuning" / "results.parquet")
    assert set(results.workload) == {"fio", "stress_ng"}


def test_selecting_everything_is_no_filter(root, tmp_path):
    service = _service(root, tmp_path)
    tuning = service.find("tuning")
    preview = service.prepare(tuning, hosts=["h1"], workloads=tuning.workloads)
    assert preview.hosts == ()
    assert preview.workloads == ()


def test_a_narrower_unification_rewrites_every_table(root, tmp_path):
    service = _service(root, tmp_path)
    tuning = service.find("tuning")
    service.write(service.prepare(tuning))
    service.write(service.prepare(tuning, workloads=["fio"]))
    out = tmp_path / "exports" / "tuning"
    assert set(pd.read_parquet(out / "results.parquet").workload) == {"fio"}
    assert set(pd.read_parquet(out / "samples.parquet").workload) <= {"fio"}
    assert set(pd.read_parquet(out / "repetitions.parquet").workload) == {"fio"}


def test_an_empty_preview_is_refused(root, tmp_path):
    service = _service(root, tmp_path)
    preview = service.prepare(service.find("tuning"), hosts=["nobody"])
    assert preview.is_empty
    assert ("Nothing to unify", "no results or samples after the filters") in (
        preview.summary_rows()
    )
    with pytest.raises(UnificationError, match="Nothing to unify"):
        service.write(preview)
    assert not (tmp_path / "exports" / "tuning").exists()


def test_the_equivalent_command_reproduces_the_choice(root, tmp_path):
    service = _service(root, tmp_path, config=tmp_path / "my config.yaml")
    tuning = service.find("tuning")
    preview = service.prepare(tuning, workloads=["fio"])
    assert preview.command == (
        f"lb runs analyze --experiment tuning --root {root} "
        f"--config '{tmp_path / 'my config.yaml'}' --workload fio"
    )
    folder = service.prepare(service.find(None))
    assert folder.command.startswith("lb runs analyze --folder --root ")


def test_summary_rows_cover_what_the_user_decides_on(root, tmp_path):
    service = _service(root, tmp_path)
    rows = dict(service.prepare(service.find("tuning")).summary_rows())
    assert rows["Experiment"] == "tuning"
    assert rows["Runs"] == "2"
    assert rows["Workloads"] == "fio, stress_ng"
    assert rows["Rows: runs"] == "2"
    assert rows["Load errors"] == "0"
    assert rows["Output"] == str(tmp_path / "exports" / "tuning")


def test_missing_pyarrow_is_reported_before_loading(root, tmp_path, monkeypatch):
    monkeypatch.setattr(unification_service, "_has_pyarrow", lambda: False)
    service = _service(root, tmp_path)
    with pytest.raises(UnificationError, match=r"linux-benchmark-lib\[controller\]"):
        service.prepare(service.find("tuning"))
