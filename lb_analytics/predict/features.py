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
