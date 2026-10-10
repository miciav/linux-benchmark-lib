# Performance Prediction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A notebook-facing library in `lb_analytics` that builds a machine feature table and a per-machine target table from unified experiments, fits per-target log-linear models, validates them leaving one machine out against two baselines, and predicts a new machine with an error range.

**Architecture:** Two modules in a new `lb_analytics/predict/` package: `features.py` (pure functions from `ExperimentData` to DataFrames) and `model.py` (fit, validation, prediction on those DataFrames). Everything public goes through `lb_analytics/api.py`. No CLI, no GUI.

**Tech Stack:** Python 3.12, pandas, numpy (`numpy.linalg.lstsq`), pytest.

**Spec:** `docs/superpowers/specs/2026-10-10-performance-prediction-design.md`

## Global Constraints

- Dependencies: pandas and numpy only, both already required. No scikit-learn.
- `lb_analytics` imports only `lb_common` (import-linter contract); the new code imports neither.
- Public names exported from `lb_analytics/api.py`: `machines`, `targets`, `fit`, `evaluate`, `loo_predictions`, `predict`, `Model`, `Prediction`, `PredictionError`.
- Every user-facing failure is a `PredictionError(ValueError)` whose message is shown as is.
- Test modules carry `pytestmark = pytest.mark.unit_analytics`.
- ruff (88 columns) and basedpyright standard must pass: `uv run pre-commit run --all-files`.
- The code below was prototyped and passes ruff, basedpyright and its tests; copy it exactly. The ruff-format hook also formats Python blocks in this file: if a pasted block looks dedented or odd, compare it with the intent before using it.

## Review Focus

1. Results of a host that has no `host_info` (the dfaas k6 load generator) — dropped from `targets`, never a crash or a `None` machine. Pinned in Task 2 (`test_targets_skip_hosts_without_host_info`).
2. A target with a zero or negative median on some machine (error counts, idle percentages) inside `evaluate` — a `skipped` row, not a `log(0)` crash. Pinned in Task 4 (`test_evaluate_skips_targets_it_cannot_fit`).
3. `host_info` missing whole categories (no disk, no cpu rows) or with malformed disk JSON — NaN features, no crash. Pinned in Task 1 (`test_machines_leaves_missing_categories_as_nan`, `test_machines_picks_the_largest_disk_and_skips_bad_json`).
4. Datasets named per repetition (`metrics-<id>-iter1-rep2`, dfaas and peva_faas) — merged into one target, not one target per repetition. Pinned in Task 2 (`test_targets_merge_datasets_named_per_repetition`).
5. `predict` on a `machines()` row (a `pd.Series` whose unused features are NaN) — works; a missing used feature raises `PredictionError`. Pinned in Task 3 (`test_predict_accepts_a_machines_row`, `test_predict_refuses_a_missing_feature`).

---

### Task 1: Machine feature table

**Files:**
- Create: `lb_analytics/predict/__init__.py` (empty)
- Create: `lb_analytics/predict/features.py`
- Modify: `lb_analytics/api.py`
- Delete (untracked, `__pycache__` only): `lb_analytics/engine/`, `lb_analytics/reporting/`
- Test: `tests/unit/lb_analytics/test_predict_features.py`

**Interfaces:**
- Produces:
  - `FEATURES: tuple[str, ...]`, `BINARY_FEATURES: frozenset[str]` (`{"disk_rotational"}`), `MACHINE_COLUMNS: list[str]`
  - `to_number(value: Any) -> float` (NaN when not a number)
  - `parse_size(text: Any) -> float` (bytes, NaN when unreadable)
  - `machines(*data: ExperimentData) -> pd.DataFrame` with columns `MACHINE_COLUMNS`: `machine`, `host`, the 12 features, `arch`, `cpu_model`, `cpu_vendor`, `virtualized`, `kernel`, `runs` (list of run ids)
  - `lb_analytics.api.machines`

- [ ] **Step 1: Housekeeping**

```bash
rm -rf lb_analytics/engine lb_analytics/reporting
git status --short lb_analytics
```

Expected: no output (both directories held only untracked `__pycache__`).

- [ ] **Step 2: Write the failing tests**

Create `tests/unit/lb_analytics/test_predict_features.py`:

```python
import json
import math
from collections.abc import Collection, Sequence
from pathlib import Path

import pandas as pd
import pytest

from lb_analytics.api import ExperimentData, LoadReport, machines
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
    assert found["machine"].tolist() == ["h1", "h1#2"]
    assert found["physical_cpus"].tolist() == [2, 4]
    assert found["runs"].tolist() == [["r1", "r3"], ["r2"]]


def test_machines_of_nothing_is_an_empty_frame() -> None:
    found = machines(_data([]))
    assert found.empty
    assert "physical_cpus" in found.columns
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/lb_analytics/test_predict_features.py -q`
Expected: collection error, `ImportError: cannot import name 'machines' from 'lb_analytics.api'`.

- [ ] **Step 4: Implement**

Create the empty `lb_analytics/predict/__init__.py`. Create `lb_analytics/predict/features.py`:

```python
"""Machine features and per-machine targets from the unified tables."""

from __future__ import annotations

import json
import math
import re
from typing import Any

import pandas as pd

from lb_analytics.unify.experiment import ExperimentData

FEATURES = (
    "logical_cpus",
    "physical_cpus",
    "threads_per_core",
    "sockets",
    "cpu_mhz",
    "bogomips",
    "l2_bytes",
    "l3_bytes",
    "mem_bytes",
    "swap_bytes",
    "disk_bytes",
    "disk_rotational",
)
BINARY_FEATURES = frozenset({"disk_rotational"})
DESCRIPTIVE = ("arch", "cpu_model", "cpu_vendor", "virtualized", "kernel")
MACHINE_COLUMNS = ["machine", "host", *FEATURES, *DESCRIPTIVE, "runs"]

_HYPERVISORS = {"QEMU", "KVM"}
_SIZE = re.compile(r"^\s*([\d.]+)\s*([KMG]i?B?|B)?", re.IGNORECASE)
_UNIT_BYTES = {"": 1, "k": 1024, "ki": 1024, "m": 1024**2, "mi": 1024**2}
_UNIT_BYTES |= {"g": 1024**3, "gi": 1024**3}


def to_number(value: Any) -> float:
    """``value`` as a float; NaN when it is missing or not a number."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def parse_size(text: Any) -> float:
    """Bytes in an lscpu size: '1 MiB (4 instances)', '512 KiB', '256K'."""
    match = _SIZE.match(str(text)) if text is not None else None
    if not match:
        return math.nan
    unit = (match.group(2) or "").lower().removesuffix("b")
    return float(match.group(1)) * _UNIT_BYTES[unit]


def machines(*data: ExperimentData) -> pd.DataFrame:
    """One row per machine: a host with one set of feature values.

    The same host seen with different features (a VM re-created with another
    size) is a different machine, named ``host#2``, ``host#3``… in order of
    first run.
    """
    info = pd.concat([d.host_info for d in data], ignore_index=True)
    if info.empty:
        return pd.DataFrame(columns=MACHINE_COLUMNS)
    runs = pd.concat([d.runs for d in data], ignore_index=True)
    started = runs.drop_duplicates("run_id").set_index("run_id")["created_at"]
    rows = []
    for (run_id, host), group in info.groupby(["run_id", "host"], sort=False):
        values = {
            (category, name): value
            for category, name, value in group[
                ["category", "name", "value"]
            ].itertuples(index=False)
        }
        rows.append(
            {
                "host": host,
                "run_id": run_id,
                "started": started.get(run_id),
                **_features(values),
            }
        )
    frame = pd.DataFrame(rows).sort_values(
        ["started", "run_id"], na_position="last", kind="stable"
    )
    seen: dict[str, int] = {}
    out = []
    for _, group in frame.groupby(["host", *FEATURES], dropna=False, sort=False):
        first = group.iloc[0]
        count = seen[first["host"]] = seen.get(first["host"], 0) + 1
        name = first["host"] if count == 1 else f"{first['host']}#{count}"
        out.append({**first.to_dict(), "machine": name, "runs": list(group["run_id"])})
    return pd.DataFrame(out, columns=MACHINE_COLUMNS)


def _features(values: dict[tuple[str, str], Any]) -> dict[str, Any]:
    def cpu(name: str) -> Any:
        return values.get(("cpu", name))

    disk = _largest_disk([v for (cat, _), v in values.items() if cat == "disk"])
    bios = str(cpu("bios_vendor_id") or "")
    return {
        "logical_cpus": to_number(cpu("logical_cpus") or cpu("cpu(s)")),
        "physical_cpus": to_number(cpu("physical_cpus")),
        "threads_per_core": to_number(cpu("thread(s)_per_core")),
        "sockets": to_number(cpu("socket(s)")),
        "cpu_mhz": to_number(cpu("cpu_max_mhz") or cpu("cpu_mhz")),
        "bogomips": to_number(cpu("bogomips")),
        "l2_bytes": parse_size(cpu("l2_cache")),
        "l3_bytes": parse_size(cpu("l3_cache")),
        "mem_bytes": to_number(values.get(("memory", "total_bytes"))),
        "swap_bytes": to_number(values.get(("memory", "swap_total_bytes"))),
        "disk_bytes": to_number(disk.get("size_bytes")),
        "disk_rotational": to_number(disk.get("rotational")),
        "arch": values.get(("kernel", "machine")),
        "cpu_model": cpu("model_name"),
        "cpu_vendor": cpu("vendor_id"),
        "virtualized": cpu("hypervisor_vendor") is not None
        or bios.upper() in _HYPERVISORS,
        "kernel": values.get(("kernel", "release")),
    }


def _largest_disk(raw: list[Any]) -> dict[str, Any]:
    disks = []
    for text in raw:
        try:
            disk = json.loads(text)
        except (TypeError, ValueError):
            continue
        if isinstance(disk, dict):
            disks.append(disk)
    return max(disks, key=lambda d: to_number(d.get("size_bytes")), default={})
```

In `lb_analytics/api.py`, add the import and the export:

```python
"""Public API surface for lb_analytics."""

from lb_analytics.predict.features import machines
from lb_analytics.unify.experiment import ExperimentData
from lb_analytics.unify.loader import load_experiment
from lb_analytics.unify.report import LoadReport

__all__ = [
    "ExperimentData",
    "LoadReport",
    "load_experiment",
    "machines",
]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/lb_analytics/test_predict_features.py -q`
Expected: exit 0, 14 passed.

- [ ] **Step 6: Lint, types, commit**

```bash
uv run ruff check lb_analytics tests/unit/lb_analytics && uv run ruff format --check lb_analytics tests/unit/lb_analytics && uv run basedpyright lb_analytics
git add lb_analytics/predict lb_analytics/api.py tests/unit/lb_analytics/test_predict_features.py
git commit -m "Machine feature table from host_info"
```

Expected: ruff "All checks passed!", basedpyright "0 errors".

---

### Task 2: Per-machine target table

**Files:**
- Modify: `lb_analytics/predict/features.py`
- Modify: `lb_analytics/api.py`
- Test: `tests/unit/lb_analytics/test_predict_features.py`

**Interfaces:**
- Consumes: `machines(*data)` and its `runs` column from Task 1.
- Produces:
  - `TARGET_COLUMNS = ["machine", "target", "workload", "metric", "unit", "median", "iqr", "n"]`
  - `targets(*data: ExperimentData) -> pd.DataFrame` with those columns; `target` is `workload/plugin/dataset/metric[dim=value,…]` with dims sorted by column name, nulls left out, and a trailing `-rep<N>` dropped from `dataset`.
  - `lb_analytics.api.targets`

- [ ] **Step 1: Write the failing tests**

In `tests/unit/lb_analytics/test_predict_features.py`, change the api import to:

```python
from lb_analytics.api import ExperimentData, LoadReport, machines, targets
```

and append:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/lb_analytics/test_predict_features.py -q`
Expected: collection error, `ImportError: cannot import name 'targets' from 'lb_analytics.api'`.

- [ ] **Step 3: Implement**

In `lb_analytics/predict/features.py`, add after `MACHINE_COLUMNS`:

```python
TARGET_COLUMNS = [
    "machine",
    "target",
    "workload",
    "metric",
    "unit",
    "median",
    "iqr",
    "n",
]
```

add after the `_UNIT_BYTES |= …` line:

```python
# dfaas and peva_faas name one dataset per repetition: metrics-<id>-iter1-rep2
_REPETITION_SUFFIX = re.compile(r"-rep\d+$")
```

add after `machines`:

```python
def targets(*data: ExperimentData) -> pd.DataFrame:
    """Median, IQR and count of every target on every machine.

    Failed repetitions are left out, and so are results of hosts with no
    ``host_info`` (they have no features to model).
    """
    found = machines(*data)
    owner = {
        (run_id, host): machine
        for machine, host, run_ids in zip(
            found["machine"], found["host"], found["runs"], strict=True
        )
        for run_id in run_ids
    }
    results = pd.concat([d.results for d in data], ignore_index=True)
    reps = pd.concat([d.repetitions for d in data], ignore_index=True)
    keys = ["run_id", "host", "workload", "repetition"]
    failed_rows = reps.loc[reps["success"].eq(False), keys]
    failed = set(failed_rows.itertuples(index=False, name=None))
    keep = [
        key not in failed for key in results[keys].itertuples(index=False, name=None)
    ]
    results = results[keep].copy()
    results["machine"] = [
        owner.get(key) for key in zip(results["run_id"], results["host"], strict=True)
    ]
    results["value"] = pd.to_numeric(results["value"], errors="coerce")
    results = results.dropna(subset=["machine", "value"])
    if results.empty:
        return pd.DataFrame(columns=TARGET_COLUMNS)
    results["target"] = _target_names(results)
    grouped = results.groupby(["machine", "target"], sort=True)
    out = grouped.agg(
        workload=("workload", "first"),
        metric=("metric", "first"),
        unit=("unit", "first"),
        median=("value", "median"),
        n=("value", "size"),
    )
    out["iqr"] = grouped["value"].quantile(0.75) - grouped["value"].quantile(0.25)
    return out.reset_index()[TARGET_COLUMNS]
```

and at the end of the file:

```python
def _target_names(results: pd.DataFrame) -> list[str]:
    dims = sorted(c for c in results.columns if c.startswith("dim_"))
    names = []
    columns = ["workload", "plugin", "dataset", "metric", *dims]
    for row in results[columns].itertuples(index=False, name=None):
        workload, plugin, dataset, metric = (str(part) for part in row[:4])
        dataset = _REPETITION_SUFFIX.sub("", dataset)
        base = f"{workload}/{plugin}/{dataset}/{metric}"
        parts = [
            f"{dim[4:]}={value}"
            for dim, value in zip(dims, row[4:], strict=True)
            if pd.notna(value)
        ]
        names.append(f"{base}[{','.join(parts)}]" if parts else base)
    return names
```

In `lb_analytics/api.py`: `from lb_analytics.predict.features import machines, targets` and add `"targets"` to `__all__` (alphabetical, after `"machines"`).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/lb_analytics/test_predict_features.py -q`
Expected: exit 0, 20 passed.

- [ ] **Step 5: Lint, types, commit**

```bash
uv run ruff check lb_analytics tests/unit/lb_analytics && uv run ruff format --check lb_analytics tests/unit/lb_analytics && uv run basedpyright lb_analytics
git add lb_analytics/predict/features.py lb_analytics/api.py tests/unit/lb_analytics/test_predict_features.py
git commit -m "Per-machine target table from results"
```

Expected: ruff "All checks passed!", basedpyright "0 errors".

---

### Task 3: Fit and predict

**Files:**
- Create: `lb_analytics/predict/model.py`
- Modify: `lb_analytics/api.py`
- Test: `tests/unit/lb_analytics/test_predict_model.py`

**Interfaces:**
- Consumes: `FEATURES`, `BINARY_FEATURES`, `to_number` from `lb_analytics.predict.features`; DataFrames shaped like `machines()` (`machine` + feature columns) and `targets()` (`TARGET_COLUMNS`).
- Produces:
  - `PredictionError(ValueError)`
  - `Model` (frozen dataclass: `target: str`, `unit: str`, `features: tuple[str, ...]`, `intercept: float`, `coefficients: dict[str, float]`, `machines: tuple[str, ...]`, `feature_ranges: dict[str, tuple[float, float]]`, `max_log_error: float`, `rel_iqr: float`; `to_json() -> str`, `Model.from_json(text) -> Model`)
  - `Prediction` (frozen dataclass: `value`, `low`, `high`: float; `unit: str`; `extrapolated: bool`)
  - `fit(machines, targets, target: str, features: Sequence[str]) -> Model`
  - `predict(model, machine: Mapping[str, Any] | pd.Series) -> Prediction`
  - private, used by Task 4: `_table(machines, targets, target, features: list[str]) -> pd.DataFrame`, `_loo(table, features: list[str]) -> pd.DataFrame` with columns `machine`, `method` (`model`/`mean`/`nearest`), `actual`, `predicted`, `pct_error`; `METHODS = ("model", "mean", "nearest")`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/lb_analytics/test_predict_model.py`:

```python
import math

import pandas as pd
import pytest

from lb_analytics.api import Model, PredictionError, fit, predict

pytestmark = pytest.mark.unit_analytics

TARGET = "fio/fio/results/iops"
CORES = (1, 2, 3, 8, 16)
NOISE = (1.0, 1.02, 0.98, 1.01, 0.99)


def _law(cores: float) -> float:
    return 50 * cores**0.9


def _frames(
    cores: tuple[int, ...] = CORES, noise: tuple[float, ...] = NOISE
) -> tuple[pd.DataFrame, pd.DataFrame]:
    names = [f"m{c}" for c in cores]
    machines = pd.DataFrame(
        {
            "machine": names,
            "physical_cpus": [float(c) for c in cores],
            "mem_bytes": [8e9] * len(cores),
            "disk_rotational": [0.0] * len(cores),
        }
    )
    targets = pd.DataFrame(
        {
            "machine": names,
            "target": TARGET,
            "workload": "fio",
            "metric": "iops",
            "unit": "op/s",
            "median": [_law(c) * n for c, n in zip(cores, noise, strict=True)],
            "iqr": [_law(c) * 0.02 for c in cores],
            "n": 3,
        }
    )
    return machines, targets


def test_fit_recovers_the_exponent() -> None:
    model = fit(*_frames(), TARGET, ["physical_cpus"])
    assert model.coefficients["physical_cpus"] == pytest.approx(0.9, abs=0.05)
    assert model.unit == "op/s"
    assert model.machines == ("m1", "m2", "m3", "m8", "m16")
    assert model.feature_ranges == {"physical_cpus": (1.0, 16.0)}
    assert 0 < model.max_log_error < 0.1
    assert model.rel_iqr == pytest.approx(0.02, rel=0.1)


def test_predict_range_contains_an_unseen_machine() -> None:
    model = fit(*_frames(), TARGET, ["physical_cpus"])
    prediction = predict(model, {"physical_cpus": 6})
    assert prediction.low < _law(6) < prediction.high
    assert prediction.value == pytest.approx(_law(6), rel=0.05)
    assert prediction.unit == "op/s"
    assert not prediction.extrapolated


def test_predict_accepts_a_machines_row() -> None:
    machines, targets = _frames()
    model = fit(machines, targets, TARGET, ["physical_cpus"])
    row = machines.iloc[2]
    assert predict(model, row).value == pytest.approx(_law(3), rel=0.05)


def test_predict_outside_the_training_range_warns() -> None:
    model = fit(*_frames(), TARGET, ["physical_cpus"])
    with pytest.warns(UserWarning, match="physical_cpus=64"):
        prediction = predict(model, {"physical_cpus": 64})
    assert prediction.extrapolated


def test_predict_refuses_a_missing_feature() -> None:
    model = fit(*_frames(), TARGET, ["physical_cpus"])
    with pytest.raises(PredictionError, match="physical_cpus"):
        predict(model, {"mem_bytes": 8e9})


def test_model_json_round_trip() -> None:
    model = fit(*_frames(), TARGET, ["physical_cpus"])
    assert Model.from_json(model.to_json()) == model


def test_fit_refuses_an_unknown_target_and_lists_similar_ones() -> None:
    with pytest.raises(PredictionError, match="similar: fio/fio/results/iops"):
        fit(*_frames(), "iops", ["physical_cpus"])
    with pytest.raises(PredictionError, match="Unknown target 'nope'"):
        fit(*_frames(), "nope", ["physical_cpus"])


def test_fit_refuses_an_unknown_feature() -> None:
    with pytest.raises(PredictionError, match="Unknown feature 'cores'"):
        fit(*_frames(), TARGET, ["cores"])


def test_fit_refuses_too_few_machines() -> None:
    machines, targets = _frames()
    with pytest.raises(PredictionError, match="at least 3"):
        fit(machines, targets.head(2), TARGET, ["physical_cpus"])


def test_fit_refuses_a_missing_feature_value() -> None:
    machines, targets = _frames()
    machines.loc[0, "physical_cpus"] = math.nan
    with pytest.raises(PredictionError, match="'physical_cpus' is missing on m1"):
        fit(machines, targets, TARGET, ["physical_cpus"])


def test_fit_refuses_a_constant_feature() -> None:
    with pytest.raises(PredictionError, match="'mem_bytes' has the same value"):
        fit(*_frames(), TARGET, ["mem_bytes"])


def test_fit_refuses_a_non_positive_target() -> None:
    machines, targets = _frames()
    targets.loc[0, "median"] = 0.0
    with pytest.raises(PredictionError, match="not positive on m1"):
        fit(machines, targets, TARGET, ["physical_cpus"])


def test_binary_feature_enters_without_log() -> None:
    machines, targets = _frames()
    machines["disk_rotational"] = [1.0, 1.0, 0.0, 0.0, 0.0]
    model = fit(machines, targets, TARGET, ["physical_cpus", "disk_rotational"])
    assert set(model.coefficients) == {"physical_cpus", "disk_rotational"}
    assert predict(model, {"physical_cpus": 2, "disk_rotational": 0}).value > 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/lb_analytics/test_predict_model.py -q`
Expected: collection error, `ImportError: cannot import name 'Model' from 'lb_analytics.api'`.

- [ ] **Step 3: Implement**

Create `lb_analytics/predict/model.py`:

```python
"""Log-linear models of one target over machine features.

With 3 to 15 machines every model is validated by leaving one machine out and
compared with two baselines: the mean of the other machines and the nearest
one on the chosen features.
"""

from __future__ import annotations

import json
import math
import warnings
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from lb_analytics.predict.features import BINARY_FEATURES, FEATURES, to_number

METHODS = ("model", "mean", "nearest")


class PredictionError(ValueError):
    """A model cannot be fitted or used; the message is meant for the user."""


@dataclass(frozen=True)
class Model:
    target: str
    unit: str
    features: tuple[str, ...]
    intercept: float
    coefficients: dict[str, float]
    machines: tuple[str, ...]
    feature_ranges: dict[str, tuple[float, float]]
    max_log_error: float
    rel_iqr: float

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, text: str) -> Model:
        raw = json.loads(text)
        raw["features"] = tuple(raw["features"])
        raw["machines"] = tuple(raw["machines"])
        raw["feature_ranges"] = {k: tuple(v) for k, v in raw["feature_ranges"].items()}
        return cls(**raw)


@dataclass(frozen=True)
class Prediction:
    value: float
    low: float
    high: float
    unit: str
    extrapolated: bool


def fit(
    machines: pd.DataFrame,
    targets: pd.DataFrame,
    target: str,
    features: Sequence[str],
) -> Model:
    """Fit ``log(median) = b0 + Σ bᵢ·log(featureᵢ)`` for one target.

    ``disk_rotational`` enters as 0/1 instead of its log. The returned model
    carries its leave-one-machine-out error, which sets the range of
    ``predict``.
    """
    features = list(features)
    table = _table(machines, targets, target, features)
    coef = _solve(_design(table, features), np.log(table["median"].to_numpy(float)))
    held_out = _loo(table, features)
    held_out = held_out[held_out["method"] == "model"]
    ratios = held_out["predicted"].to_numpy(float) / held_out["actual"].to_numpy(float)
    log_errors = np.abs(np.log(ratios))
    rel_iqr = (table["iqr"] / table["median"]).fillna(0.0)
    return Model(
        target=target,
        unit=_unit(table),
        features=tuple(features),
        intercept=float(coef[0]),
        coefficients={f: float(c) for f, c in zip(features, coef[1:], strict=True)},
        machines=tuple(table["machine"]),
        feature_ranges={
            f: (float(table[f].min()), float(table[f].max())) for f in features
        },
        max_log_error=float(log_errors.max()),
        rel_iqr=float(rel_iqr.median()),
    )


def predict(model: Model, machine: Mapping[str, Any] | pd.Series) -> Prediction:
    """Predict ``model.target`` for one machine, with the model's range.

    The range is the worst leave-one-machine-out error plus the target's
    run-to-run noise. A feature outside the training range warns and sets
    ``extrapolated``.
    """
    log_value = model.intercept
    extrapolated = False
    for feature in model.features:
        x = to_number(machine.get(feature))
        if math.isnan(x) or (x <= 0 and feature not in BINARY_FEATURES):
            raise PredictionError(
                f"Feature '{feature}' is missing or not positive "
                f"({machine.get(feature)!r})."
            )
        low, high = model.feature_ranges[feature]
        if not low <= x <= high:
            extrapolated = True
            warnings.warn(
                f"{feature}={x:g} is outside the training range "
                f"[{low:g}, {high:g}]: the prediction is an extrapolation.",
                stacklevel=2,
            )
        term = x if feature in BINARY_FEATURES else math.log(x)
        log_value += model.coefficients[feature] * term
    value = math.exp(log_value)
    spread = math.exp(model.max_log_error + math.log1p(model.rel_iqr))
    return Prediction(value, value / spread, value * spread, model.unit, extrapolated)


def _table(
    machines: pd.DataFrame, targets: pd.DataFrame, target: str, features: list[str]
) -> pd.DataFrame:
    """The target's rows joined to the machines' features, checked for fitting."""
    if not features:
        raise PredictionError("Pick at least one feature.")
    unknown = [f for f in features if f not in FEATURES]
    if unknown:
        raise PredictionError(
            f"Unknown feature '{unknown[0]}'; available: {', '.join(FEATURES)}."
        )
    rows = targets[targets["target"] == target]
    if rows.empty:
        similar = sorted(t for t in targets["target"].unique() if target in t)[:5]
        hint = f"; similar: {', '.join(similar)}" if similar else ""
        raise PredictionError(f"Unknown target '{target}'{hint}.")
    table = rows.merge(machines[["machine", *features]], on="machine", how="left")
    needed = len(features) + 2
    if len(table) < needed:
        raise PredictionError(
            f"'{target}' was measured on {len(table)} machine(s); "
            f"{len(features)} feature(s) need at least {needed}."
        )
    for feature in features:
        missing = table.loc[table[feature].isna(), "machine"].tolist()
        if missing:
            raise PredictionError(
                f"Feature '{feature}' is missing on {', '.join(missing)}."
            )
        if feature not in BINARY_FEATURES:
            bad = table.loc[table[feature] <= 0, "machine"].tolist()
            if bad:
                raise PredictionError(
                    f"Feature '{feature}' is not positive on {', '.join(bad)}."
                )
        if table[feature].nunique() < 2:
            raise PredictionError(
                f"Feature '{feature}' has the same value on every machine, "
                "so it cannot explain differences between them."
            )
    bad = table.loc[table["median"] <= 0, "machine"].tolist()
    if bad:
        raise PredictionError(
            f"'{target}' is not positive on {', '.join(bad)}; "
            "a log model needs positive values."
        )
    return table.reset_index(drop=True)


def _design(table: pd.DataFrame, features: list[str]) -> np.ndarray:
    columns = [
        table[f].to_numpy(float)
        if f in BINARY_FEATURES
        else np.log(table[f].to_numpy(float))
        for f in features
    ]
    return np.column_stack([np.ones(len(table)), *columns])


def _solve(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    return np.linalg.lstsq(x, y, rcond=None)[0]


def _loo(table: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    """Predict each machine from the others with the model and both baselines."""
    y = np.log(table["median"].to_numpy(float))
    x = _design(table, features)
    z = x[:, 1:]
    rows = []
    for i in range(len(table)):
        rest = np.arange(len(table)) != i
        sd = z[rest].std(axis=0)
        use = sd > 0
        # ponytail: with every feature constant on the rest, nearest is the first one
        distance = (((z[rest][:, use] - z[i, use]) / sd[use]) ** 2).sum(axis=1)
        guesses = {
            "model": float(x[i] @ _solve(x[rest], y[rest])),
            "mean": float(y[rest].mean()),
            "nearest": float(y[rest][int(np.argmin(distance))]),
        }
        actual = math.exp(y[i])
        for method, log_guess in guesses.items():
            predicted = math.exp(log_guess)
            rows.append(
                {
                    "machine": table["machine"].iat[i],
                    "method": method,
                    "actual": actual,
                    "predicted": predicted,
                    "pct_error": 100 * (predicted - actual) / actual,
                }
            )
    return pd.DataFrame(rows)


def _unit(table: pd.DataFrame) -> str:
    unit = table["unit"].dropna()
    return str(unit.iloc[0]) if not unit.empty else ""
```

In `lb_analytics/api.py`:

```python
"""Public API surface for lb_analytics."""

from lb_analytics.predict.features import machines, targets
from lb_analytics.predict.model import (
    Model,
    Prediction,
    PredictionError,
    fit,
    predict,
)
from lb_analytics.unify.experiment import ExperimentData
from lb_analytics.unify.loader import load_experiment
from lb_analytics.unify.report import LoadReport

__all__ = [
    "ExperimentData",
    "LoadReport",
    "Model",
    "Prediction",
    "PredictionError",
    "fit",
    "load_experiment",
    "machines",
    "predict",
    "targets",
]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/lb_analytics/test_predict_model.py -q`
Expected: exit 0, 13 passed.

- [ ] **Step 5: Lint, types, commit**

```bash
uv run ruff check lb_analytics tests/unit/lb_analytics && uv run ruff format --check lb_analytics tests/unit/lb_analytics && uv run basedpyright lb_analytics
git add lb_analytics/predict/model.py lb_analytics/api.py tests/unit/lb_analytics/test_predict_model.py
git commit -m "Log-linear model per target, with leave-one-machine-out range"
```

Expected: ruff "All checks passed!", basedpyright "0 errors".

---

### Task 4: Evaluation against baselines, and docs

**Files:**
- Modify: `lb_analytics/predict/model.py`
- Modify: `lb_analytics/api.py`
- Modify: `docs/reference/analytics.md`
- Test: `tests/unit/lb_analytics/test_predict_model.py`

**Interfaces:**
- Consumes: `_table`, `_loo`, `METHODS`, `PredictionError` from Task 3.
- Produces:
  - `EVALUATE_COLUMNS = ["target", "method", "machines", "median_abs_pct_error", "max_abs_pct_error", "beats_baselines", "note"]`
  - `evaluate(machines, targets, features: Sequence[str], targets_filter: str | None = None) -> pd.DataFrame`
  - `loo_predictions(machines, targets, target: str, features: Sequence[str]) -> pd.DataFrame`
  - `lb_analytics.api.evaluate`, `lb_analytics.api.loo_predictions`

- [ ] **Step 1: Write the failing tests**

In `tests/unit/lb_analytics/test_predict_model.py`, change the api import to:

```python
from lb_analytics.api import (
    Model,
    PredictionError,
    evaluate,
    fit,
    loo_predictions,
    predict,
)
```

and append:

```python
def test_nearest_baseline_uses_the_closest_machine() -> None:
    machines, targets = _frames()
    held_out = loo_predictions(machines, targets, TARGET, ["physical_cpus"])
    row = held_out[(held_out.machine == "m3") & (held_out.method == "nearest")]
    m2 = targets.loc[targets.machine == "m2", "median"].item()
    assert row["predicted"].item() == pytest.approx(m2)


def test_loo_predictions_has_every_machine_and_method() -> None:
    held_out = loo_predictions(*_frames(), TARGET, ["physical_cpus"])
    assert len(held_out) == len(CORES) * 3
    assert set(held_out.method) == {"model", "mean", "nearest"}


def test_evaluate_says_the_model_beats_the_baselines() -> None:
    report = evaluate(*_frames(), ["physical_cpus"])
    model_row = report[report.method == "model"].iloc[0]
    assert model_row["beats_baselines"]
    assert model_row["median_abs_pct_error"] < 5
    assert model_row["machines"] == len(CORES)
    assert set(report.method) == {"model", "mean", "nearest"}


def test_evaluate_skips_targets_it_cannot_fit() -> None:
    machines, targets = _frames()
    sparse = targets.head(2).assign(target="dd/dd/results/bw")
    zero = targets.assign(target="stream/stream/results/errors", median=0.0)
    report = evaluate(machines, pd.concat([targets, sparse, zero]), ["physical_cpus"])
    skipped = report[report.method == "skipped"].set_index("target")
    assert "at least 3" in skipped.loc["dd/dd/results/bw", "note"]
    assert "not positive" in skipped.loc["stream/stream/results/errors", "note"]
    assert (report[report.target == TARGET].method != "skipped").all()


def test_evaluate_filters_targets_by_text() -> None:
    machines, targets = _frames()
    other = targets.assign(target="dd/dd/results/bw")
    report = evaluate(machines, pd.concat([targets, other]), ["physical_cpus"], "dd/")
    assert set(report.target) == {"dd/dd/results/bw"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/lb_analytics/test_predict_model.py -q`
Expected: collection error, `ImportError: cannot import name 'evaluate' from 'lb_analytics.api'`.

- [ ] **Step 3: Implement**

In `lb_analytics/predict/model.py`, add after `METHODS`:

```python
EVALUATE_COLUMNS = [
    "target",
    "method",
    "machines",
    "median_abs_pct_error",
    "max_abs_pct_error",
    "beats_baselines",
    "note",
]
```

and after `predict`:

```python
def loo_predictions(
    machines: pd.DataFrame,
    targets: pd.DataFrame,
    target: str,
    features: Sequence[str],
) -> pd.DataFrame:
    """Every held-out prediction behind ``evaluate`` for one target.

    One row per machine and method: ``actual``, ``predicted``, ``pct_error``.
    """
    features = list(features)
    return _loo(_table(machines, targets, target, features), features)


def evaluate(
    machines: pd.DataFrame,
    targets: pd.DataFrame,
    features: Sequence[str],
    targets_filter: str | None = None,
) -> pd.DataFrame:
    """Leave-one-machine-out errors of the model and both baselines.

    One row per target and method. Targets that cannot be fitted get one
    ``skipped`` row with the reason in ``note``.
    """
    features = list(features)
    names = sorted(targets["target"].unique())
    if targets_filter:
        names = [name for name in names if targets_filter in name]
    rows: list[dict[str, Any]] = []
    for name in names:
        count = int((targets["target"] == name).sum())
        try:
            table = _table(machines, targets, name, features)
        except PredictionError as exc:
            rows.append(
                {
                    "target": name,
                    "method": "skipped",
                    "machines": count,
                    "note": str(exc),
                }
            )
            continue
        errors = _loo(table, features).groupby("method")["pct_error"]
        medians = errors.apply(lambda e: e.abs().median())
        maxima = errors.apply(lambda e: e.abs().max())
        wins = bool(medians["model"] < min(medians["mean"], medians["nearest"]))
        rows.extend(
            {
                "target": name,
                "method": method,
                "machines": count,
                "median_abs_pct_error": float(medians[method]),
                "max_abs_pct_error": float(maxima[method]),
                "beats_baselines": wins if method == "model" else None,
                "note": "",
            }
            for method in METHODS
        )
    return pd.DataFrame(rows, columns=EVALUATE_COLUMNS)
```

In `lb_analytics/api.py`, import `evaluate` and `loo_predictions` from `lb_analytics.predict.model` alongside the others, and add `"evaluate"` and `"loo_predictions"` to `__all__` in alphabetical order.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/lb_analytics -q`
Expected: exit 0, no FAILED lines (18 in `test_predict_model.py`, 20 in `test_predict_features.py`, plus the existing analytics tests).

- [ ] **Step 5: Document**

Append to `docs/reference/analytics.md`:

````markdown
## Prediction

`lb_analytics.api` can answer, per benchmark metric, how much of a machine's
performance its specifications explain, and predict a machine that was not
benchmarked. It is a library for notebooks; there is no command.

    from lb_analytics.api import evaluate, fit, load_experiment, machines, predict, targets

    catalog = RunCatalogService(output_dir)
    data = [load_experiment(catalog.get_experiment(e).runs) for e in experiment_ids]
    m, t = machines(*data), targets(*data)
    report = evaluate(m, t, ["physical_cpus", "mem_bytes"], targets_filter="stress_ng")
    model = fit(m, t, "stress_ng/stress_ng/results/bogo_ops_s[stressor=cpu]", ["physical_cpus"])
    predict(model, new_machine_row)  # Prediction(value, low, high, unit, extrapolated)

- `machines` has one row per machine: a host with one set of features
  (cores, MHz, caches, memory, disk). The same host re-created with another
  size is another machine (`host#2`).
- `targets` has one row per machine and target, with the median over the
  successful repetitions, the IQR and the count.
- `fit` is a log-linear regression: a coefficient of 0.9 on `physical_cpus`
  means doubling the cores multiplies the metric by about 1.87.
- `evaluate` leaves each machine out in turn and compares the model with the
  mean of the other machines and with the nearest one on the chosen features.
  A model is worth using only where `beats_baselines` is true.
- `predict` gives a range: the worst error seen leaving machines out, plus the
  run-to-run noise. A feature outside the training range warns that the
  prediction is an extrapolation.

Limits: the machines must differ in the chosen features (identical VMs explain
nothing); use one to three features with fewer than 15 machines; the kernel
reports virtio disks as rotational, so `disk_rotational` is unreliable on VMs.
The features of a machine come from any run on it, so a short `baseline` run is
enough to predict it.

::: lb_analytics.predict.features.machines
::: lb_analytics.predict.features.targets
::: lb_analytics.predict.model.fit
::: lb_analytics.predict.model.evaluate
::: lb_analytics.predict.model.loo_predictions
::: lb_analytics.predict.model.predict
````

(The outer fence is four backticks only to show the snippet here; the doc gets the content between them. The example is indented by four spaces, like the existing one in that file.)

Run: `uv run --all-extras mkdocs build --strict --site-dir "$(mktemp -d)"`
Expected: exit 0, no warnings about `lb_analytics.predict`.

- [ ] **Step 6: Full checks and commit**

```bash
uv run pre-commit run --all-files
uv run pytest tests/unit -q > .superpowers/predict-unit.log 2>&1; echo "exit $?"; grep -E "FAILED|ERROR" .superpowers/predict-unit.log | head
git add lb_analytics/predict/model.py lb_analytics/api.py docs/reference/analytics.md tests/unit/lb_analytics/test_predict_model.py
git commit -m "Leave-one-machine-out evaluation against mean and nearest baselines"
```

Expected: every pre-commit hook Passed or Skipped; pytest `exit 0` and no FAILED/ERROR lines (the output ends with a marker table that hides the passed count: rely on the exit code).
