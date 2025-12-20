from datetime import datetime
import json
from pathlib import Path

from lb_controller.services.run_catalog_service import RunCatalogService


def _write_journal(path: Path, tasks, created_at: str = "2024-01-01T00:00:00") -> None:
    payload = {"metadata": {"created_at": created_at}, "tasks": tasks}
    path.write_text(json.dumps(payload))


def test_get_run_reads_journal_metadata_and_tasks(tmp_path: Path):
    output_dir = tmp_path / "benchmark_results"
    run_dir = output_dir / "run-1"
    run_dir.mkdir(parents=True)
    journal_path = run_dir / "run_journal.json"
    _write_journal(journal_path, [{"host": "hostA", "workload": "wl1"}])

    report_dir = tmp_path / "reports"
    export_dir = tmp_path / "data_exports"
    (report_dir / "run-1").mkdir(parents=True)
    (export_dir / "run-1").mkdir(parents=True)

    svc = RunCatalogService(output_dir, report_dir, export_dir)
    info = svc.get_run("run-1")

    assert info is not None
    assert info.hosts == ["hostA"]
    assert info.workloads == ["wl1"]
    assert info.created_at == datetime.fromisoformat("2024-01-01T00:00:00")
    assert info.report_root == (report_dir / "run-1").resolve()
    assert info.data_export_root == (export_dir / "run-1").resolve()


def test_get_run_falls_back_to_directories(tmp_path: Path):
    output_dir = tmp_path / "benchmark_results"
    run_dir = output_dir / "run-2"
    workload_dir = run_dir / "host1" / "workload1"
    workload_dir.mkdir(parents=True)

    svc = RunCatalogService(output_dir)
    info = svc.get_run("run-2")

    assert info is not None
    assert info.hosts == ["host1"]
    assert info.workloads == ["workload1"]
