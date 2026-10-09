"""Every plugin must declare every file and every numeric column it exports.

Runs each plugin's export on real outputs captured from Multipass runs
(tests/fixtures/plugin_outputs), then checks its describe_datasets().
"""

import json
import re
import shutil
from pathlib import Path

import pandas as pd
import pytest

from lb_common.api import DatasetDescriptor, plan_wide
from lb_plugins.api import create_registry

pytestmark = pytest.mark.unit_plugins

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "plugin_outputs"

# Workloads whose declarations are complete. Later tasks extend this list.
DECLARED: list[str] = [
    "sysbench",
    "baseline",
    "stress_ng",
    "unixbench",
    "fio",
    "dd",
    "hpl",
    "stream",
    "yabs",
    "geekbench",
    "pts_ramspeed",
    "pts_compress_7zip",
    "dfaas",
    "peva_faas",
]


def _export(tmp_path: Path, workload: str) -> Path:
    work = tmp_path / workload
    shutil.copytree(FIXTURES / workload, work)
    results = json.loads((work / f"{workload}_results.json").read_text())
    plugin = create_registry().get(workload)
    plugin.export_results_to_csv(results, work, "fixture-run", workload)
    return work


def _covered(d: DatasetDescriptor, frame: pd.DataFrame) -> set[str]:
    covered = {*d.keys, "repetition"}
    covered |= {c for c in frame.columns if any(re.fullmatch(p, c) for p in d.exclude)}
    if d.shape == "wide":
        plan = plan_wide(d, list(frame.columns))
        assert not plan.unmatched_specs, f"{d.name}: {plan.unmatched_specs}"
        for metric in plan.metrics:
            assert pd.api.types.is_numeric_dtype(frame[metric.column]), (
                f"{d.name}: metric column {metric.column} is not numeric"
            )
        covered |= {m.column for m in plan.metrics}
    else:
        covered |= {v.column for v in d.value_columns}
        covered |= {c for c in (d.value_column,) if c}
    return covered


@pytest.mark.parametrize("workload", DECLARED)
def test_plugin_declares_every_file_and_numeric_column(
    tmp_path: Path, workload: str
) -> None:
    work = _export(tmp_path, workload)
    descriptors = create_registry().get(workload).describe_datasets(work, workload)
    declared_files: set[Path] = set()
    for d in descriptors:
        files = sorted(work.glob(d.path))
        assert files, f"{d.name}: {d.path!r} matches no file"
        declared_files |= {f.relative_to(work) for f in files}
        if d.target_table != "results":
            continue
        for path in files:
            frame = pd.read_csv(path)
            numeric = {
                c for c in frame.columns if pd.api.types.is_numeric_dtype(frame[c])
            }
            missing = numeric - _covered(d, frame)
            assert not missing, f"{path.name}: undeclared numeric {sorted(missing)}"
    # Collector files under rep*/ are the runner's, not the plugin's.
    exported = {
        p.relative_to(work)
        for p in work.rglob("*.csv")
        if not p.relative_to(work).parts[0].startswith("rep")
    }
    undeclared = sorted(exported - declared_files)
    assert not undeclared, f"undeclared: {undeclared}"


def _metrics(tmp_path: Path, workload: str) -> dict[tuple, str | None]:
    """Map (metric, sorted dims) -> unit for the plugin's main CSV."""
    work = _export(tmp_path, workload)
    [d, *_] = create_registry().get(workload).describe_datasets(work, workload)
    frame = pd.read_csv(work / d.path)
    return {
        (m.metric, tuple(sorted(m.dims.items()))): m.unit
        for m in plan_wide(d, list(frame.columns)).metrics
    }


def test_stress_ng_declares_per_stressor_metrics(tmp_path: Path) -> None:
    metrics = _metrics(tmp_path, "stress_ng")
    assert metrics[("bogo_ops", (("stressor", "cpu"),))] == "ops"
    assert metrics[("bogo_ops_per_s_real", (("stressor", "vm"),))] == "ops/s"


def test_unixbench_reads_units_from_its_unit_columns(tmp_path: Path) -> None:
    work = _export(tmp_path, "unixbench")
    [d] = create_registry().get("unixbench").describe_datasets(work, "unixbench")
    plan = plan_wide(d, list(pd.read_csv(work / d.path).columns))
    result = next(m for m in plan.metrics if m.metric == "result")
    assert result.unit_column == f"generator_{result.dims['test']}_unit"
    assert any(m.metric == "index_score" for m in plan.metrics)


def test_fio_splits_direction_into_a_dimension(tmp_path: Path) -> None:
    metrics = _metrics(tmp_path, "fio")
    assert metrics[("iops", (("direction", "read"),))] == "IOPS"
    assert metrics[("lat_ms", (("direction", "write"),))] == "ms"


def test_stream_keeps_seconds_and_drops_millisecond_copies(tmp_path: Path) -> None:
    metrics = _metrics(tmp_path, "stream")
    assert metrics[("best_rate_mb_s", (("kernel", "triad"),))] == "MB/s"
    assert ("avg_time_ms", (("kernel", "copy"),)) not in metrics


def test_yabs_declares_iperf_as_long(tmp_path: Path) -> None:
    work = _export(tmp_path, "yabs")
    descriptors = create_registry().get("yabs").describe_datasets(work, "yabs")
    iperf = {d.name: d for d in descriptors}["yabs_iperf"]
    assert iperf.shape == "long"
    assert {v.column: v.unit for v in iperf.value_columns} == {
        "send_mbits": "Mbit/s",
        "recv_mbits": "Mbit/s",
        "latency_ms": "ms",
    }


def test_pts_reads_values_and_units_from_composite_rows(tmp_path: Path) -> None:
    work = _export(tmp_path, "pts_compress_7zip")
    descriptors = (
        create_registry()
        .get("pts_compress_7zip")
        .describe_datasets(work, "pts_compress_7zip")
    )
    by_name = {d.name: d for d in descriptors}
    assert by_name["pts_compress_7zip_pts"].target_table == "ignore"
    values = by_name["pts_compress_7zip_pts_results"]
    assert (values.metric_column, values.value_column, values.unit_column) == (
        "test",
        "value",
        "scale",
    )


def test_faas_metrics_files_carry_config_and_iteration(tmp_path: Path) -> None:
    work = _export(tmp_path, "dfaas")
    descriptors = create_registry().get("dfaas").describe_datasets(work, "dfaas")
    metrics_files = [d for d in descriptors if d.path.startswith("metrics/")]
    assert metrics_files
    assert {"config_id", "iteration", "repetition"} <= set(metrics_files[0].fixed)
    ignored = {d.path for d in descriptors if d.target_table == "ignore"}
    assert {"results.csv", "skipped.csv", "index.csv"} <= ignored
