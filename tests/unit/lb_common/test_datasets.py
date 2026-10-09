from pathlib import Path

import pytest
from pydantic import ValidationError

from lb_common.api import (
    DatasetDescriptor,
    DatasetManifest,
    MetricSpec,
    ValueColumn,
    plan_wide,
    read_manifest,
    write_manifest,
)

pytestmark = pytest.mark.unit_common


def _wide(**kwargs) -> DatasetDescriptor:
    return DatasetDescriptor(name="d", path="d.csv", shape="wide", **kwargs)


def test_pattern_must_name_a_metric_group() -> None:
    with pytest.raises(ValidationError, match="metric"):
        MetricSpec(pattern=r"^gen_(?P<x>.+)$")


def test_metric_needs_exactly_one_of_column_or_pattern() -> None:
    with pytest.raises(ValidationError):
        MetricSpec()
    with pytest.raises(ValidationError):
        MetricSpec(column="a", pattern=r"(?P<metric>a)")


def test_timeseries_requires_time_column() -> None:
    with pytest.raises(ValidationError, match="time_column"):
        DatasetDescriptor(name="t", path="t.csv", shape="timeseries")


def test_long_requires_one_value_layout() -> None:
    with pytest.raises(ValidationError):
        DatasetDescriptor(name="l", path="l.csv", shape="long")
    DatasetDescriptor(
        name="l", path="l.csv", shape="long", value_columns=[ValueColumn(column="v")]
    )
    DatasetDescriptor(
        name="l", path="l.csv", shape="long", metric_column="m", value_column="v"
    )


def test_host_info_long_needs_only_value_column() -> None:
    d = DatasetDescriptor(
        name="system_info",
        path="system_info.csv",
        shape="long",
        table="host_info",
        keys=["category", "name"],
        value_column="value",
    )
    assert d.target_table == "host_info"


def test_target_table_defaults_follow_shape() -> None:
    assert _wide().target_table == "results"
    ts = DatasetDescriptor(name="t", path="t.csv", shape="timeseries", time_column="ts")
    assert ts.target_table == "samples"


def test_manifest_round_trip(tmp_path: Path) -> None:
    manifest = DatasetManifest(
        workload="fio",
        plugin="fio",
        repetitions="fio_results.json",
        datasets=[_wide(metrics=[MetricSpec(column="read_iops", unit="IOPS")])],
    )
    path = write_manifest(tmp_path, manifest)
    assert path.name == "datasets.json"
    assert read_manifest(tmp_path) == manifest


def test_plan_wide_extracts_metric_and_dimensions() -> None:
    d = _wide(
        keys=["repetition"],
        metrics=[
            MetricSpec(
                pattern=r"^generator_(?P<stressor>.+?)_(?P<metric>bogo_ops)$",
                unit="ops",
            )
        ],
        exclude=["generator_stdout"],
    )
    plan = plan_wide(
        d, ["repetition", "generator_cpu_bogo_ops", "generator_stdout", "run_id"]
    )
    [metric] = plan.metrics
    assert (metric.column, metric.metric, metric.unit) == (
        "generator_cpu_bogo_ops",
        "bogo_ops",
        "ops",
    )
    assert metric.dims == {"stressor": "cpu"}
    assert plan.ignored == ["run_id"]
    assert plan.unmatched_specs == []


def test_plan_wide_resolves_unit_column_template_and_reports_unmatched() -> None:
    d = _wide(
        metrics=[
            MetricSpec(
                pattern=r"^g_(?P<test>.+)_(?P<metric>result)$",
                unit_column="g_{test}_unit",
            ),
            MetricSpec(column="missing", unit="s"),
        ]
    )
    plan = plan_wide(d, ["g_dhry_result", "g_dhry_unit"])
    assert plan.metrics[0].unit_column == "g_dhry_unit"
    assert plan.unmatched_specs == ["missing"]


def test_plan_wide_column_metric_uses_explicit_name() -> None:
    d = _wide(metrics=[MetricSpec(column="generator_x", name="x", unit="s")])
    assert plan_wide(d, ["generator_x"]).metrics[0].metric == "x"
