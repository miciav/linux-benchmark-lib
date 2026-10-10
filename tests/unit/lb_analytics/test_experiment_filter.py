import pandas as pd
import pytest

from lb_analytics.api import ExperimentData, LoadReport

pytestmark = pytest.mark.unit_analytics


def _data() -> ExperimentData:
    rows = [("r", h, w) for h in ("h1", "h2") for w in ("fio", "dd")]
    frame = pd.DataFrame(rows, columns=["run_id", "host", "workload"])
    return ExperimentData(
        runs=pd.DataFrame({"run_id": ["r"]}),
        host_info=pd.DataFrame({"run_id": ["r", "r"], "host": ["h1", "h2"]}),
        repetitions=frame,
        results=frame,
        samples=frame,
        report=LoadReport(),
    )


def test_no_filter_keeps_everything() -> None:
    data = _data().filter()
    assert data.row_counts == {
        "runs": 1,
        "host_info": 2,
        "repetitions": 4,
        "results": 4,
        "samples": 4,
    }


def test_host_filter_applies_to_every_table_with_a_host() -> None:
    data = _data().filter(hosts=["h1"])
    assert set(data.host_info.host) == {"h1"}
    assert set(data.repetitions.host) == {"h1"}
    assert set(data.results.host) == {"h1"}
    assert set(data.samples.host) == {"h1"}
    assert len(data.runs) == 1


def test_workload_filter_leaves_host_info_alone() -> None:
    data = _data().filter(workloads=["fio"])
    assert set(data.results.workload) == {"fio"}
    assert len(data.host_info) == 2


def test_both_filters_combine() -> None:
    data = _data().filter(hosts=["h2"], workloads=["dd"])
    assert data.results[["host", "workload"]].values.tolist() == [["h2", "dd"]]
    assert data.results.index.tolist() == [0]


def test_filter_keeps_the_load_report() -> None:
    original = _data()
    assert original.filter(hosts=["h1"]).report is original.report
