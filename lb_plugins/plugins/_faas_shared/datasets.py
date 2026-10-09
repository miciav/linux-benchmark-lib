"""Tidy export and dataset declarations shared by dfaas and peva_faas.

``results.csv`` keeps the legacy layout (one row per configuration, columns per
function). ``results_long.csv`` restates it as one row per configuration x
function x metric, which is what ``lb_analytics`` loads.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

from lb_common.api import DatasetDescriptor, MetricSpec
from lb_plugins.plugins._faas_shared.config_enumerator import config_id

# Units follow queries.yml and the k6 summary: CPU is 100 * cores, memory in
# bytes, Scaphandre power in microwatts, k6 latency in milliseconds.
_FUNCTION_METRICS = {
    "success_rate": ("success_rate_function_{}", "ratio"),
    "cpu_usage": ("cpu_usage_function_{}", "%"),
    "ram_usage": ("ram_usage_function_{}", "B"),
    "power_usage": ("power_usage_function_{}", "uW"),
    "replicas": ("replica_{}", "count"),
    "overloaded": ("overloaded_function_{}", "flag"),
    "medium_latency": ("medium_latency_function_{}", "ms"),
}
_NODE_METRICS = {
    "cpu_usage_idle_node": "%",
    "cpu_usage_node": "%",
    "ram_usage_idle_node": "B",
    "ram_usage_node": "B",
    "ram_usage_idle_node_percentage": "%",
    "ram_usage_node_percentage": "%",
    "power_usage_idle_node": "uW",
    "power_usage_node": "uW",
    "rest_seconds": "s",
    "overloaded_node": "flag",
}
_LONG_COLUMNS = [
    "repetition",
    "config_id",
    "function",
    "rate",
    "metric",
    "value",
    "unit",
]
_METRICS_FILE = re.compile(
    r"^metrics-(?P<config_id>[0-9a-f]+)-iter(?P<iteration>\d+)-rep(?P<rep>\d+)\.csv$"
)


def long_rows(results: list[dict[str, Any]], prefix: str) -> list[dict[str, Any]]:
    """Restate the legacy results rows as configuration x function x metric."""
    rows: list[dict[str, Any]] = []
    for entry in results:
        gen = entry.get("generator_result") or {}
        functions = list(gen.get(f"{prefix}_functions") or [])
        for result in gen.get(f"{prefix}_results") or []:
            active = [f for f in functions if result.get(f"function_{f}")]
            pairs = [(f, _rate(result.get(f"rate_function_{f}"))) for f in active]
            known = [(f, rate) for f, rate in pairs if rate is not None]
            base = {
                "repetition": entry.get("repetition"),
                "config_id": config_id(known),
            }
            for function, rate in pairs:
                for metric, (column, unit) in _FUNCTION_METRICS.items():
                    rows.append(
                        {
                            **base,
                            "function": function,
                            "rate": "" if rate is None else rate,
                            "metric": metric,
                            "value": result.get(column.format(function), ""),
                            "unit": unit,
                        }
                    )
            for metric, unit in _NODE_METRICS.items():
                if metric in result:
                    rows.append(
                        {
                            **base,
                            "function": "",
                            "rate": "",
                            "metric": metric,
                            "value": result[metric],
                            "unit": unit,
                        }
                    )
    return rows


def _rate(value: Any) -> int | None:
    """A configured rate, or None when the row does not carry one."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def write_results_long(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_LONG_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def faas_datasets(output_dir: Path) -> list[DatasetDescriptor]:
    """Declare what a FaaS export wrote into ``output_dir``."""
    datasets = [
        DatasetDescriptor(
            name="results_legacy", path="results.csv", shape="wide", table="ignore"
        ),
        DatasetDescriptor(
            name="skipped", path="skipped.csv", shape="wide", table="ignore"
        ),
        DatasetDescriptor(name="index", path="index.csv", shape="wide", table="ignore"),
        DatasetDescriptor(
            name="results_long",
            path="results_long.csv",
            shape="long",
            keys=["config_id", "function", "rate"],
            metric_column="metric",
            value_column="value",
            unit_column="unit",
        ),
    ]
    for path in sorted((output_dir / "metrics").glob("metrics-*.csv")):
        match = _METRICS_FILE.match(path.name)
        if match is None:
            continue
        datasets.append(
            DatasetDescriptor(
                name=path.stem,
                path=f"metrics/{path.name}",
                shape="wide",
                fixed={
                    "repetition": int(match["rep"]),
                    "config_id": match["config_id"],
                    "iteration": int(match["iteration"]),
                },
                metrics=[
                    MetricSpec(
                        pattern=r"^(?P<metric>cpu_usage)_function_(?P<function>.+)$",
                        unit="%",
                    ),
                    MetricSpec(
                        pattern=r"^(?P<metric>ram_usage)_function_(?P<function>.+)$",
                        unit="B",
                    ),
                    MetricSpec(
                        pattern=r"^(?P<metric>power_usage)_function_(?P<function>.+)$",
                        unit="uW",
                    ),
                    MetricSpec(column="cpu_usage_node", unit="%"),
                    MetricSpec(column="ram_usage_node", unit="B"),
                    MetricSpec(column="ram_usage_node_pct", unit="%"),
                    MetricSpec(column="power_usage_node", unit="uW"),
                ],
            )
        )
    return datasets
