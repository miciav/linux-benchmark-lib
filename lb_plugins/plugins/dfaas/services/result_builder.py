"""Result row builder for DFaaS generator output."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from ..config import DfaasOverloadConfig
from .cooldown import MetricsSnapshot


@dataclass(frozen=True)
class DfaasResultBuilder:
    """Builds result and skipped rows for DFaaS runs."""

    overload: DfaasOverloadConfig

    def build_result_row(
        self,
        all_functions: list[str],
        config_pairs: list[tuple[str, int]],
        summary_metrics: dict[str, dict[str, float]],
        replicas: dict[str, int],
        metrics: dict[str, Any],
        idle_snapshot: MetricsSnapshot,
        rest_seconds: int,
    ) -> tuple[dict[str, Any], bool]:
        row: dict[str, Any] = {}
        config_map = {name: rate for name, rate in config_pairs}
        overloaded_any = False
        avg_success_rate = 0.0
        present_count = 0

        for name in all_functions:
            if name in config_map:
                success = summary_metrics.get(name, {}).get("success_rate", 1.0)
                latency = summary_metrics.get(name, {}).get("avg_latency", 0.0)
                cpu = metrics["functions"].get(name, {}).get("cpu", float("nan"))
                ram = metrics["functions"].get(name, {}).get("ram", float("nan"))
                power = metrics["functions"].get(name, {}).get("power", float("nan"))
                replica = int(replicas.get(name, 0))
                overloaded_function = int(
                    success < self.overload.success_rate_function_min
                    or replica >= self.overload.replicas_overload_threshold
                )
                if overloaded_function:
                    overloaded_any = True
                avg_success_rate += success
                present_count += 1

                row[f"function_{name}"] = name
                row[f"rate_function_{name}"] = config_map[name]
                row[f"success_rate_function_{name}"] = self._format_float(success)
                row[f"cpu_usage_function_{name}"] = self._format_float(cpu)
                row[f"ram_usage_function_{name}"] = self._format_float(ram)
                row[f"power_usage_function_{name}"] = self._format_float(power)
                row[f"replica_{name}"] = replica
                row[f"overloaded_function_{name}"] = overloaded_function
                row[f"medium_latency_function_{name}"] = int(latency)
            else:
                row[f"function_{name}"] = ""
                row[f"rate_function_{name}"] = ""
                row[f"success_rate_function_{name}"] = ""
                row[f"cpu_usage_function_{name}"] = ""
                row[f"ram_usage_function_{name}"] = ""
                row[f"power_usage_function_{name}"] = ""
                row[f"replica_{name}"] = ""
                row[f"overloaded_function_{name}"] = ""
                row[f"medium_latency_function_{name}"] = ""

        avg_success_rate = (
            avg_success_rate / present_count if present_count else 1.0
        )
        node_cpu = float(metrics.get("cpu_usage_node", float("nan")))
        node_ram = float(metrics.get("ram_usage_node", float("nan")))
        node_ram_pct = float(metrics.get("ram_usage_node_pct", float("nan")))
        node_power = float(metrics.get("power_usage_node", float("nan")))

        overloaded_node = int(
            avg_success_rate < self.overload.success_rate_node_min
            or node_cpu > self.overload.cpu_overload_pct_of_capacity
            or node_ram_pct > self.overload.ram_overload_pct
            or overloaded_any
        )

        row["cpu_usage_idle_node"] = self._format_float(idle_snapshot.cpu)
        row["cpu_usage_node"] = self._format_float(node_cpu)
        row["ram_usage_idle_node"] = self._format_float(idle_snapshot.ram)
        row["ram_usage_node"] = self._format_float(node_ram)
        row["ram_usage_idle_node_percentage"] = self._format_float(idle_snapshot.ram_pct)
        row["ram_usage_node_percentage"] = self._format_float(node_ram_pct)
        row["power_usage_idle_node"] = self._format_float(idle_snapshot.power)
        row["power_usage_node"] = self._format_float(node_power)
        row["rest_seconds"] = rest_seconds
        row["overloaded_node"] = overloaded_node

        return row, bool(overloaded_node)

    def build_skipped_row(
        self, all_functions: list[str], config_pairs: list[tuple[str, int]]
    ) -> dict[str, Any]:
        row: dict[str, Any] = {}
        config_map = {name: rate for name, rate in config_pairs}
        for name in all_functions:
            if name in config_map:
                row[f"function_{name}"] = name
                row[f"rate_function_{name}"] = config_map[name]
            else:
                row[f"function_{name}"] = ""
                row[f"rate_function_{name}"] = ""
        return row

    @staticmethod
    def _format_float(value: float) -> str:
        if math.isnan(value):
            return "nan"
        return f"{value:.3f}"
