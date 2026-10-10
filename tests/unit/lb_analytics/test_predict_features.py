import json
import math
from collections.abc import Collection, Sequence
from pathlib import Path

import pandas as pd
import pytest

from lb_analytics.api import ExperimentData, LoadReport, machines, targets
from lb_analytics.predict.features import parse_size

pytestmark = pytest.mark.unit_analytics

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "plugin_outputs"
    / "_host"
    / "system_info.csv"
)
HOST_INFO_COLUMNS = ["run_id", "host", "category", "name", "value"]
RESULT_COLUMNS = ["run_id", "host", "workload", "plugin", "repetition", "dataset"]
RESULT_COLUMNS += ["metric", "value", "unit"]


def _info(run_id: str, host: str, cpus: int, mem: int = 8_000_000_000) -> list[tuple]:
    return [
        (run_id, host, "cpu", "physical_cpus", str(cpus)),
        (run_id, host, "memory", "total_bytes", str(mem)),
    ]


def _data(
    info: Sequence[tuple],
    results: Sequence[tuple] = (),
    failed: Collection[tuple] = frozenset(),
) -> ExperimentData:
    """``results`` rows are (run_id, host, repetition, value) of fio iops."""
    host_info = pd.DataFrame(list(info), columns=HOST_INFO_COLUMNS)
    runs = pd.DataFrame({"run_id": list(dict.fromkeys(host_info["run_id"]))})
    runs["created_at"] = pd.to_datetime([f"2026-10-0{i + 1}" for i in range(len(runs))])
    rows = [
        (run, host, "fio", "fio", rep, "results", "iops", value, "op/s")
        for run, host, rep, value in results
    ]
    frame = pd.DataFrame(rows, columns=RESULT_COLUMNS)
    reps = frame[["run_id", "host", "workload", "repetition"]].drop_duplicates()
    reps["success"] = [
        (run, host, rep) not in failed
        for run, host, rep in zip(reps.run_id, reps.host, reps.repetition, strict=True)
    ]
    return ExperimentData(
        runs=runs,
        host_info=host_info,
        repetitions=reps,
        results=frame,
        samples=pd.DataFrame(),
        report=LoadReport(),
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1 MiB (4 instances)", 1024**2),
        ("512 KiB", 512 * 1024),
        ("256K", 256 * 1024),
        ("32 MiB (1 instance)", 32 * 1024**2),
        ("4 GiB", 4 * 1024**3),
    ],
)
def test_parse_size_reads_lscpu_sizes(text: str, expected: int) -> None:
    assert parse_size(text) == expected


@pytest.mark.parametrize("text", ["", None, "n/a"])
def test_parse_size_is_nan_when_unreadable(text: str | None) -> None:
    assert math.isnan(parse_size(text))


def test_machines_reads_the_real_arm_host_info() -> None:
    raw = pd.read_csv(FIXTURE, dtype=str)
    info = [("r1", "h1", *row) for row in raw.itertuples(index=False, name=None)]
    row = machines(_data(info)).iloc[0]
    assert row["machine"] == "h1"
    assert row["logical_cpus"] == 4
    assert row["physical_cpus"] == 4
    assert row["threads_per_core"] == 1
    assert row["sockets"] == 1
    assert row["bogomips"] == 2000.0
    assert row["mem_bytes"] == 8302465024
    assert row["swap_bytes"] == 0
    assert row["disk_bytes"] == 42949672960
    assert row["disk_rotational"] == 1
    assert math.isnan(row["cpu_mhz"])
    assert math.isnan(row["l2_bytes"])
    assert row["arch"] == "aarch64"
    assert row["cpu_model"] == "Cortex-A725"
    assert row["virtualized"]
    assert row["kernel"] == "6.8.0-142-generic"
    assert row["runs"] == ["r1"]


def test_machines_reads_x86_mhz_and_caches() -> None:
    info = [
        ("r1", "h1", "cpu", "cpu_max_mhz", "4200.0000"),
        ("r1", "h1", "cpu", "cpu_mhz", "800.000"),
        ("r1", "h1", "cpu", "l2_cache", "2 MiB (8 instances)"),
        ("r1", "h1", "cpu", "l3_cache", "16 MiB (1 instance)"),
        ("r1", "h1", "cpu", "hypervisor_vendor", "KVM"),
        ("r2", "h2", "cpu", "cpu_mhz", "2400.000"),
    ]
    found = machines(_data(info)).set_index("machine")
    assert found.loc["h1", "cpu_mhz"] == 4200.0
    assert found.loc["h1", "l2_bytes"] == 2 * 1024**2
    assert found.loc["h1", "l3_bytes"] == 16 * 1024**2
    assert found.loc["h1", "virtualized"]
    assert found.loc["h2", "cpu_mhz"] == 2400.0
    assert not found.loc["h2", "virtualized"]


def test_machines_picks_the_largest_disk_and_skips_bad_json() -> None:
    small = json.dumps({"name": "vda", "size_bytes": 10, "rotational": True})
    large = json.dumps({"name": "nvme0n1", "size_bytes": 500, "rotational": False})
    info = [
        ("r1", "h1", "disk", "vda", small),
        ("r1", "h1", "disk", "nvme0n1", large),
        ("r1", "h1", "disk", "broken", "{not json"),
    ]
    row = machines(_data(info)).iloc[0]
    assert row["disk_bytes"] == 500
    assert row["disk_rotational"] == 0


def test_machines_leaves_missing_categories_as_nan() -> None:
    row = machines(_data([("r1", "h1", "memory", "total_bytes", "1024")])).iloc[0]
    assert row["mem_bytes"] == 1024
    assert math.isnan(row["physical_cpus"])
    assert math.isnan(row["disk_bytes"])
    assert not row["virtualized"]


def test_same_host_with_another_size_is_another_machine() -> None:
    info = _info("r1", "h1", 2) + _info("r2", "h1", 4) + _info("r3", "h1", 2)
    found = machines(_data(info))
    names = found["machine"].tolist()
    assert len(set(names)) == 2
    assert all(name.startswith("h1#") for name in names)
    assert found["physical_cpus"].tolist() == [2, 4]
    assert found["runs"].tolist() == [["r1", "r3"], ["r2"]]


def test_a_host_with_one_size_keeps_its_name() -> None:
    info = _info("r1", "h1", 2) + _info("r2", "h1", 2)
    assert machines(_data(info))["machine"].tolist() == ["h1"]


def test_variant_names_do_not_depend_on_the_other_experiments() -> None:
    small = _data(_info("r1", "h1", 2), [("r1", "h1", 1, 10.0)])
    large = _data(_info("r2", "h1", 4), [("r2", "h1", 1, 40.0)])
    both = machines(small, large)
    joined = targets(large).merge(both, on="machine")
    assert (joined["physical_cpus"] == 4).all()
    assert set(machines(large, small)["machine"]) == set(both["machine"])


def test_feature_drift_does_not_split_a_machine() -> None:
    info = _info("r1", "h1", 2, mem=8_000_000_000) + _info(
        "r2", "h1", 2, mem=8_000_300_000
    )
    info += [("r1", "h1", "cpu", "bogomips", "4000.00")]
    info += [("r2", "h1", "cpu", "bogomips", "3990.00")]
    info += [("r2", "h1", "memory", "swap_total_bytes", "2147483648")]
    found = machines(_data(info))
    assert found["machine"].tolist() == ["h1"]
    assert found["runs"].tolist() == [["r1", "r2"]]


def test_machines_ignore_missing_values() -> None:
    info = [
        ("r1", "h1", "cpu", "logical_cpus", None),
        ("r1", "h1", "cpu", "cpu(s)", "4"),
        ("r1", "h1", "cpu", "hypervisor_vendor", None),
        ("r1", "h1", "cpu", "bios_vendor_id", None),
        ("r1", "h1", "cpu", "cpu_max_mhz", None),
    ]
    data = _data(info)
    data.host_info["value"] = data.host_info["value"].astype("string")
    row = machines(data).iloc[0]
    assert row["logical_cpus"] == 4
    assert math.isnan(row["cpu_mhz"])
    assert not row["virtualized"]


def test_machines_of_nothing_is_an_empty_frame() -> None:
    found = machines(_data([]))
    assert found.empty
    assert "physical_cpus" in found.columns


def test_targets_summarise_repetitions_per_machine() -> None:
    info = _info("r1", "h1", 2) + _info("r2", "h2", 4)
    results = [("r1", "h1", 1, 10.0), ("r1", "h1", 2, 20.0), ("r1", "h1", 3, 30.0)]
    results += [("r2", "h2", 1, 40.0)]
    found = targets(_data(info, results)).set_index("machine")
    assert found.loc["h1", "target"] == "fio/fio/results/iops"
    assert found.loc["h1", "median"] == 20.0
    assert found.loc["h1", "iqr"] == 10.0
    assert found.loc["h1", "n"] == 3
    assert found.loc["h1", "unit"] == "op/s"
    assert found.loc["h2", "median"] == 40.0


def test_targets_leave_out_failed_repetitions() -> None:
    results = [("r1", "h1", 1, 10.0), ("r1", "h1", 2, 1000.0)]
    found = targets(_data(_info("r1", "h1", 2), results, failed={("r1", "h1", 2)}))
    assert found["median"].tolist() == [10.0]
    assert found["n"].tolist() == [1]


def test_targets_name_includes_dimensions() -> None:
    data = _data(_info("r1", "h1", 2), [("r1", "h1", 1, 10.0), ("r1", "h1", 1, 20.0)])
    data.results["dim_mode"] = ["randread", "write"]
    data.results["dim_block_size"] = ["4k", None]
    names = sorted(targets(data)["target"])
    assert names == [
        "fio/fio/results/iops[block_size=4k,mode=randread]",
        "fio/fio/results/iops[mode=write]",
    ]


def test_targets_skip_hosts_without_host_info() -> None:
    results = [("r1", "h1", 1, 10.0), ("r1", "load-generator", 1, 99.0)]
    found = targets(_data(_info("r1", "h1", 2), results))
    assert found["machine"].tolist() == ["h1"]


def test_targets_combine_several_experiments() -> None:
    first = _data(_info("r1", "h1", 2), [("r1", "h1", 1, 10.0)])
    second = _data(_info("r9", "h2", 4), [("r9", "h2", 1, 20.0)])
    assert sorted(targets(first, second)["machine"]) == ["h1", "h2"]


def test_targets_merge_datasets_named_per_repetition() -> None:
    data = _data(_info("r1", "h1", 2), [("r1", "h1", 1, 10.0), ("r1", "h1", 2, 30.0)])
    data.results["dataset"] = ["metrics-abc-iter1-rep1", "metrics-abc-iter1-rep2"]
    found = targets(data)
    assert found["target"].tolist() == ["fio/fio/metrics-abc-iter1/iops"]
    assert found["n"].tolist() == [2]
