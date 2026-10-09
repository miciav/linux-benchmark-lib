import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from lb_analytics.api import load_experiment
from lb_common.api import RunInfo
from lb_plugins.api import create_registry
from lb_runner.api import write_host_manifest, write_workload_manifest

pytestmark = pytest.mark.unit_analytics

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "plugin_outputs"


def _run(
    root: Path, run_id: str, hosts: dict[str, list[str]], journal: bool = True
) -> RunInfo:
    """Lay out a collected run from the fixtures and write its manifests."""
    run_root = root / run_id
    for host, workloads in hosts.items():
        host_dir = run_root / host if host != "localhost" else run_root
        host_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(FIXTURES / "_host" / "system_info.csv", host_dir)
        write_host_manifest(host_dir)
        for workload in workloads:
            work = host_dir / workload
            shutil.copytree(FIXTURES / workload, work)
            plugin = create_registry().get(workload)
            results = json.loads((work / f"{workload}_results.json").read_text())
            plugin.export_results_to_csv(results, work, run_id, workload)
            write_workload_manifest(plugin, work, workload)
    if journal:
        shutil.copy(FIXTURES / "_run" / "run_journal.json", run_root)
    return RunInfo(
        run_id=run_id,
        output_root=run_root,
        report_root=None,
        data_export_root=None,
        hosts=list(hosts),
        workloads=[],
        created_at=None,
        journal_path=None,
    )


def test_two_runs_two_hosts_unify_into_five_tables(tmp_path: Path) -> None:
    runs = [
        _run(tmp_path, "r1", {"h1": ["stress_ng", "fio"], "h2": ["stress_ng"]}),
        _run(tmp_path, "r2", {"h1": ["yabs", "pts_compress_7zip", "dfaas"]}),
    ]
    data = load_experiment(runs)
    assert not data.report.errors, data.report.errors
    assert not data.report.undeclared_files
    assert set(data.runs.run_id) == {"r1", "r2"}
    assert set(data.host_info.host) == {"h1", "h2"}
    results = data.results
    stress = results[(results.workload == "stress_ng") & (results.host == "h1")]
    cpu_ops = stress[(stress.metric == "bogo_ops") & (stress.dim_stressor == "cpu")]
    assert cpu_ops.iloc[0]["value"] == pytest.approx(18800.0)
    yabs = set(results[results.workload == "yabs"].dataset)
    assert yabs == {"yabs_plugin", "yabs_iperf"}
    assert {"dim_config_id", "dim_function"} <= set(results.columns)
    assert set(data.samples.collector) == {"PSUtilCollector", "CLICollector"}
    assert set(data.repetitions.columns) >= {
        "run_id",
        "host",
        "workload",
        "repetition",
        "success",
    }


def test_absent_dimensions_are_real_nulls(tmp_path: Path) -> None:
    data = load_experiment([_run(tmp_path, "r1", {"h1": ["stress_ng", "fio"]})])
    fio = data.results[data.results.workload == "fio"]
    assert fio["dim_stressor"].isna().all()
    assert not (fio["dim_stressor"].astype(str) == "nan").any()


def test_local_layout_is_attributed_to_localhost(tmp_path: Path) -> None:
    data = load_experiment([_run(tmp_path, "r1", {"localhost": ["fio"]})])
    assert set(data.results.host) == {"localhost"}
    assert set(data.host_info.host) == {"localhost"}


def test_missing_declared_file_fails_only_its_dataset(tmp_path: Path) -> None:
    run = _run(tmp_path, "r1", {"h1": ["yabs"]})
    (run.output_root / "h1" / "yabs" / "yabs_iperf.csv").unlink()
    data = load_experiment([run])
    assert any("yabs_iperf" in e["message"] for e in data.report.errors)
    assert "yabs_plugin" in set(data.results.dataset)


def test_run_without_journal_still_loads(tmp_path: Path) -> None:
    data = load_experiment([_run(tmp_path, "r1", {"h1": ["fio"]}, journal=False)])
    assert data.runs.iloc[0]["run_id"] == "r1"
    assert pd.isna(data.runs.iloc[0]["config_hash"])
    assert any("run_journal.json" in w["message"] for w in data.report.warnings)
    assert not data.results.empty


def test_workload_without_manifest_is_not_loadable(tmp_path: Path) -> None:
    run = _run(tmp_path, "r1", {"h1": ["fio"]})
    (run.output_root / "h1" / "fio" / "datasets.json").unlink()
    data = load_experiment([run])
    assert data.report.not_loadable == [str(run.output_root / "h1" / "fio")]
    assert data.is_empty


def test_undeclared_csv_is_reported(tmp_path: Path) -> None:
    run = _run(tmp_path, "r1", {"h1": ["fio"]})
    extra = run.output_root / "h1" / "fio" / "extra.csv"
    extra.write_text("a\n1\n")
    data = load_experiment([run])
    assert data.report.undeclared_files == [str(extra)]


def test_parquet_round_trip(tmp_path: Path) -> None:
    data = load_experiment([_run(tmp_path, "r1", {"h1": ["stress_ng"]})])
    paths = data.to_parquet(tmp_path / "out")
    assert sorted(p.name for p in paths) == [
        "host_info.parquet",
        "load_report.json",
        "repetitions.parquet",
        "results.parquet",
        "runs.parquet",
        "samples.parquet",
    ]
    back = pd.read_parquet(tmp_path / "out" / "results.parquet")
    assert len(back) == len(data.results)


def test_faas_rate_dimension_is_an_integer_string(tmp_path: Path) -> None:
    data = load_experiment([_run(tmp_path, "r1", {"h1": ["dfaas"]})])
    rates = set(data.results["dim_rate"].dropna())
    assert rates and rates <= {"1", "5"}


def test_unreadable_repetitions_file_is_a_report_error(tmp_path: Path) -> None:
    run = _run(tmp_path, "r1", {"h1": ["fio"]})
    (run.output_root / "h1" / "fio" / "fio_results.json").write_text('{"a": 1}')
    data = load_experiment([run])
    assert any("repetitions" in e["message"] for e in data.report.errors)
