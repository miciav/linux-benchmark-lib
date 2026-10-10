"""Machine features and per-machine targets from the unified tables."""

from __future__ import annotations

import hashlib
import json
import math
import re
import warnings
from collections import Counter
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

# What identifies a machine: features that do not drift between its runs.
# Memory and disk are compared in whole GiB (MemTotal moves a little across
# kernels); bogomips, the current MHz and swap are left out.
_IDENTITY = (
    "logical_cpus",
    "physical_cpus",
    "threads_per_core",
    "sockets",
    "l2_bytes",
    "l3_bytes",
    "disk_rotational",
)
_GIB = 1024**3
_HYPERVISORS = {"QEMU", "KVM"}
_SIZE = re.compile(r"^\s*([\d.]+)\s*([KMG]i?B?|B)?", re.IGNORECASE)
_UNIT_BYTES = {"": 1, "k": 1024, "ki": 1024, "m": 1024**2, "mi": 1024**2}
_UNIT_BYTES |= {"g": 1024**3, "gi": 1024**3}
# dfaas and peva_faas name one dataset per repetition: metrics-<id>-iter1-rep2
_REPETITION_SUFFIX = re.compile(r"-rep\d+$")


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
    """One row per machine: a host with one set of identifying features.

    A host seen with one size is named after the host. A host seen with
    several sizes (a VM re-created) gives one machine per size, named
    ``host#<hash of its features>`` so the name does not depend on which
    experiments are passed. Feature values come from the machine's first run.
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
            if not pd.isna(value)
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
    frame["mem_gib"] = (frame["mem_bytes"] / _GIB).round()
    frame["disk_gib"] = (frame["disk_bytes"] / _GIB).round()
    keys = ["host", *_IDENTITY, "mem_gib", "disk_gib"]
    groups = list(frame.groupby(keys, dropna=False, sort=False))
    sizes = Counter(key[0] for key, _ in groups)
    out = []
    for key, group in groups:
        host = str(key[0])
        name = host if sizes[host] == 1 else f"{host}#{_digest(key[1:])}"
        first = group.iloc[0].to_dict()
        out.append({**first, "machine": name, "runs": list(group["run_id"])})
    return pd.DataFrame(out, columns=MACHINE_COLUMNS)


def targets(*data: ExperimentData) -> pd.DataFrame:
    """Median, IQR and count of every target on every machine.

    Failed repetitions are left out. A run whose ``host_info`` is missing
    counts for its host's machine when the host has only one; otherwise (a
    host never described, or one with several sizes) its results are left out
    with a warning, since they have no features to model.
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
    by_host = found.groupby("host")["machine"].unique()
    results["machine"] = [
        owner.get((run_id, host))
        or (by_host[host][0] if host in by_host and len(by_host[host]) == 1 else None)
        for run_id, host in zip(results["run_id"], results["host"], strict=True)
    ]
    unowned = results.loc[results["machine"].isna(), "host"].unique().tolist()
    if unowned:
        warnings.warn(
            f"Results of {', '.join(map(str, unowned))} are left out: no "
            "host_info tells which machine produced them.",
            stacklevel=2,
        )
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


def _digest(values: tuple[Any, ...]) -> str:
    text = repr(tuple(to_number(v) for v in values))
    return hashlib.sha256(text.encode()).hexdigest()[:4]


def _largest_disk(raw: list[Any]) -> dict[str, Any]:
    disks = []
    for text in raw:
        try:
            disk = json.loads(text)
        except (TypeError, ValueError):
            continue
        if isinstance(disk, dict) and not math.isnan(to_number(disk.get("size_bytes"))):
            disks.append(disk)
    return max(disks, key=lambda d: to_number(d.get("size_bytes")), default={})


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
