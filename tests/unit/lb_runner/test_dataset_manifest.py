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
