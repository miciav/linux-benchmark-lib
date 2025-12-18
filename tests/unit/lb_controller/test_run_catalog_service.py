"""Unit tests for RunCatalogService."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from lb_controller.services.run_catalog_service import RunCatalogService

pytestmark = [pytest.mark.controller]


def _write_journal(path: Path, created_at: str, tasks: list[dict]) -> None:
    data = {"run_id": path.parent.name, "tasks": tasks, "metadata": {"created_at": created_at}}
    path.write_text(json.dumps(data))


def test_list_runs_and_get_run(tmp_path: Path) -> None:
    output_root = tmp_path / "benchmark_results"
    report_root = tmp_path / "reports"
    export_root = tmp_path / "data_exports"
    output_root.mkdir()
    report_root.mkdir()
    export_root.mkdir()

    run_a = output_root / "run-20240101-000000"
    run_b = output_root / "run-20240102-000000"
    for run_dir in (run_a, run_b):
        (run_dir / "host1" / "stress_ng").mkdir(parents=True)
        (run_dir / "host1" / "system_info.csv").write_text("ok")

    _write_journal(
        run_a / "run_journal.json",
        "2024-01-01T00:00:00",
        [{"host": "host1", "workload": "stress_ng", "repetition": 1}],
    )
    _write_journal(
        run_b / "run_journal.json",
        "2024-01-02T00:00:00",
        [{"host": "host1", "workload": "stress_ng", "repetition": 1}],
    )

    catalog = RunCatalogService(output_root, report_root, export_root)
    runs = catalog.list_runs()
    assert [r.run_id for r in runs] == [run_b.name, run_a.name]

    run_info = catalog.get_run(run_a.name)
    assert run_info is not None
    assert run_info.run_id == run_a.name
    assert run_info.output_root == run_a.resolve()
    assert run_info.report_root == (report_root / run_a.name).resolve()
    assert run_info.data_export_root == (export_root / run_a.name).resolve()
    assert run_info.hosts == ["host1"]
    assert run_info.workloads == ["stress_ng"]
    assert run_info.created_at == datetime.fromisoformat("2024-01-01T00:00:00")


def test_get_run_fallbacks_when_no_journal(tmp_path: Path) -> None:
    output_root = tmp_path / "benchmark_results"
    output_root.mkdir()
    run_dir = output_root / "run-20240101-000000"
    (run_dir / "hostX" / "fio").mkdir(parents=True)

    catalog = RunCatalogService(output_root)
    info = catalog.get_run(run_dir.name)
    assert info is not None
    assert info.hosts == ["hostX"]
    assert info.workloads == ["fio"]

