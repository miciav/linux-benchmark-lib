import json
import shutil
from pathlib import Path

import pytest

from lb_common.api import read_manifest
from lb_plugins.api import create_registry
from lb_runner.api import write_host_manifest, write_workload_manifest
from lb_runner.services.results import export_plugin_results

pytestmark = pytest.mark.unit_runner

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "plugin_outputs"


def test_workload_manifest_merges_plugin_and_collector_datasets(
    tmp_path: Path,
) -> None:
    work = tmp_path / "stress_ng"
    shutil.copytree(FIXTURES / "stress_ng", work)
    plugin = create_registry().get("stress_ng")
    write_workload_manifest(plugin, work, "stress_ng")
    manifest = read_manifest(work)
    assert (manifest.workload, manifest.plugin) == ("stress_ng", "stress_ng")
    assert manifest.repetitions == "stress_ng_results.json"
    by_name = {d.name: d for d in manifest.datasets}
    assert "stress_ng_plugin" in by_name
    psutil = by_name["stress_ng_rep1_PSUtilCollector"]
    assert psutil.shape == "timeseries"
    assert psutil.fixed == {"repetition": 1, "collector": "PSUtilCollector"}
    assert psutil.path == "rep1/stress_ng_rep1_PSUtilCollector.csv"


def test_workload_manifest_without_plugin_keeps_collectors(tmp_path: Path) -> None:
    work = tmp_path / "fio"
    shutil.copytree(FIXTURES / "fio", work)
    write_workload_manifest(None, work, "fio")
    manifest = read_manifest(work)
    assert manifest.plugin is None
    assert manifest.datasets
    assert all(d.shape == "timeseries" for d in manifest.datasets)


def test_host_manifest_declares_system_info(tmp_path: Path) -> None:
    write_host_manifest(tmp_path)
    [dataset] = read_manifest(tmp_path).datasets
    assert (dataset.path, dataset.target_table) == ("system_info.csv", "host_info")


def test_export_plugin_results_writes_the_manifest(tmp_path: Path) -> None:
    work = tmp_path / "sysbench"
    shutil.copytree(FIXTURES / "sysbench", work)
    results = json.loads((work / "sysbench_results.json").read_text())
    plugin = create_registry().get("sysbench")
    export_plugin_results(plugin, results, work, "sysbench", "r1")
    assert (work / "datasets.json").exists()


def test_collector_clock_fields_are_excluded(tmp_path: Path) -> None:
    from lb_runner.services.dataset_manifest import collector_datasets

    work = tmp_path / "stress_ng"
    shutil.copytree(FIXTURES / "stress_ng", work)
    [cli] = [
        d for d in collector_datasets(work, "stress_ng") if "CLICollector" in d.name
    ]
    import re

    for column in ("time_hour", "time_second", "uptime_days", "uptime_total_seconds"):
        assert any(re.fullmatch(p, column) for p in cli.exclude), column
    assert not any(re.fullmatch(p, "load_1m") for p in cli.exclude)
