from pathlib import Path

import pandas as pd
import pytest

from lb_analytics.unify.readers import SourceContext, read_dataset
from lb_analytics.unify.report import LoadReport
from lb_common.api import DatasetDescriptor, MetricSpec, ValueColumn

pytestmark = pytest.mark.unit_analytics

CTX = SourceContext(run_id="r1", host="h1", workload="w", plugin="p")


def _csv(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "data.csv"
    path.write_text(text)
    return path


def test_wide_turns_columns_into_metric_rows_with_dims(tmp_path: Path) -> None:
    d = DatasetDescriptor(
        name="s",
        path="data.csv",
        shape="wide",
        keys=["repetition"],
        metrics=[
            MetricSpec(pattern=r"^g_(?P<stressor>[a-z]+)_(?P<metric>ops)$", unit="ops")
        ],
    )
    path = _csv(
        tmp_path, "repetition,g_cpu_ops,g_vm_ops,run_id\n1,10,20,r1\n2,11,,r1\n"
    )
    report = LoadReport()
    frame = read_dataset(d, path, CTX, report)
    assert frame is not None
    assert sorted(frame["dim_stressor"]) == ["cpu", "cpu", "vm"]
    assert set(frame["unit"]) == {"ops"}
    row = frame[(frame.repetition == 2) & (frame.dim_stressor == "cpu")].iloc[0]
    assert (row["metric"], row["value"], row["dataset"]) == ("ops", 11.0, "s")
    assert report.missing_values == {"data.csv": 1}
    assert report.ignored_columns == {"data.csv": ["run_id"]}


def test_wide_rejects_a_non_numeric_metric_without_partial_rows(
    tmp_path: Path,
) -> None:
    d = DatasetDescriptor(
        name="s", path="data.csv", shape="wide", metrics=[MetricSpec(column="x")]
    )
    report = LoadReport()
    path = _csv(tmp_path, "repetition,x\n1,1.5\n2,fast\n")
    assert read_dataset(d, path, CTX, report) is None
    [error] = report.errors
    assert "x" in error["message"] and "1 non-numeric" in error["message"]


def test_wide_unit_column_is_read_per_row(tmp_path: Path) -> None:
    d = DatasetDescriptor(
        name="u",
        path="data.csv",
        shape="wide",
        metrics=[
            MetricSpec(
                pattern=r"^g_(?P<test>.+)_(?P<metric>result)$",
                unit_column="g_{test}_unit",
            )
        ],
    )
    path = _csv(tmp_path, "repetition,g_dhry_result,g_dhry_unit\n1,7.5,lps\n")
    frame = read_dataset(d, path, CTX, LoadReport())
    assert frame is not None and frame.iloc[0]["unit"] == "lps"


def test_long_value_columns(tmp_path: Path) -> None:
    d = DatasetDescriptor(
        name="iperf",
        path="data.csv",
        shape="long",
        keys=["provider"],
        value_columns=[
            ValueColumn(column="send", unit="Mbit/s"),
            ValueColumn(column="lat", unit="ms"),
        ],
    )
    path = _csv(tmp_path, "repetition,provider,send,lat\n1,A,900,30\n")
    frame = read_dataset(d, path, CTX, LoadReport())
    assert frame is not None
    assert set(zip(frame.metric, frame.unit, frame.value, strict=True)) == {
        ("send", "Mbit/s", 900.0),
        ("lat", "ms", 30.0),
    }
    assert set(frame.dim_provider) == {"A"}


def test_long_metric_and_unit_columns(tmp_path: Path) -> None:
    d = DatasetDescriptor(
        name="pts",
        path="data.csv",
        shape="long",
        keys=["description"],
        metric_column="test",
        value_column="value",
        unit_column="scale",
    )
    text = "repetition,test,description,value,scale\n1,pts/x,Copy,5.0,MB/s\n"
    frame = read_dataset(d, _csv(tmp_path, text), CTX, LoadReport())
    assert frame is not None
    assert frame.iloc[0][["metric", "unit", "dim_description"]].tolist() == [
        "pts/x",
        "MB/s",
        "Copy",
    ]


def test_timeseries_melts_numeric_columns(tmp_path: Path) -> None:
    d = DatasetDescriptor(
        name="ps",
        path="data.csv",
        shape="timeseries",
        time_column="timestamp",
        fixed={"repetition": 1, "collector": "PSUtilCollector"},
    )
    text = (
        "timestamp,cpu_percent,time,collector\n"
        "2026-10-08 22:43:18,86.3,22:43:18,PSUtilCollector\n"
    )
    frame = read_dataset(d, _csv(tmp_path, text), CTX, LoadReport())
    assert frame is not None
    assert frame.columns.tolist() == [
        "run_id",
        "host",
        "workload",
        "repetition",
        "collector",
        "timestamp",
        "metric",
        "value",
    ]
    assert frame.iloc[0][["collector", "metric", "value"]].tolist() == [
        "PSUtilCollector",
        "cpu_percent",
        86.3,
    ]
    assert pd.api.types.is_datetime64_any_dtype(frame["timestamp"])


def test_host_info_keeps_text_values(tmp_path: Path) -> None:
    d = DatasetDescriptor(
        name="system_info",
        path="data.csv",
        shape="long",
        table="host_info",
        keys=["category", "name"],
        value_column="value",
    )
    text = "category,name,value\ncpu,model,Cortex-X925\nmem,total,8\n"
    frame = read_dataset(d, _csv(tmp_path, text), CTX, LoadReport())
    assert frame is not None
    assert frame.columns.tolist() == ["run_id", "host", "category", "name", "value"]
    assert frame["value"].tolist() == ["Cortex-X925", "8"]
