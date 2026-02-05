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
        config_map = {name: rate for name, rate in config_pairs}
        row, overloaded_any, avg_success_rate = self._build_function_rows(
            all_functions, config_map, summary_metrics, replicas, metrics
        )
        node_cpu, node_ram, node_ram_pct, node_power = self._extract_node_metrics(
            metrics
        )
        overloaded_node = self._is_node_overloaded(
            avg_success_rate, node_cpu, node_ram_pct, overloaded_any
        )
        row.update(
            self._build_node_rows(
                idle_snapshot,
                node_cpu,
                node_ram,
                node_ram_pct,
                node_power,
                rest_seconds,
                overloaded_node,
            )
        )
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

    def _build_function_rows(
        self,
        all_functions: list[str],
        config_map: dict[str, int],
        summary_metrics: dict[str, dict[str, float]],
        replicas: dict[str, int],
        metrics: dict[str, Any],
    ) -> tuple[dict[str, Any], bool, float]:
        row: dict[str, Any] = {}
        overloaded_any = False
        success_total = 0.0
        present_count = 0

        for name in all_functions:
            func_row, success, overloaded = self._build_function_row(
                name, config_map, summary_metrics, replicas, metrics
            )
            row.update(func_row)
            if overloaded:
                overloaded_any = True
            if success is not None:
                success_total += success
                present_count += 1

        avg_success_rate = success_total / present_count if present_count else 1.0
        return row, overloaded_any, avg_success_rate

    def _build_function_row(
        self,
        name: str,
        config_map: dict[str, int],
        summary_metrics: dict[str, dict[str, float]],
        replicas: dict[str, int],
        metrics: dict[str, Any],
    ) -> tuple[dict[str, Any], float | None, bool]:
        if name not in config_map:
            return (
                self._empty_function_row(name),
                None,
                False,
            )

        success = summary_metrics.get(name, {}).get("success_rate", 1.0)
        latency = summary_metrics.get(name, {}).get("avg_latency", 0.0)
        function_metrics = metrics.get("functions", {}).get(name, {})
        cpu = function_metrics.get("cpu", float("nan"))
        ram = function_metrics.get("ram", float("nan"))
        power = function_metrics.get("power", float("nan"))
        replica = int(replicas.get(name, 0))
        overloaded = success < self.overload.success_rate_function_min
        overloaded = overloaded or replica >= self.overload.replicas_overload_threshold
        row = {
            f"function_{name}": name,
            f"rate_function_{name}": config_map[name],
            f"success_rate_function_{name}": self._format_float(success),
            f"cpu_usage_function_{name}": self._format_float(cpu),
            f"ram_usage_function_{name}": self._format_float(ram),
            f"power_usage_function_{name}": self._format_float(power),
            f"replica_{name}": replica,
            f"overloaded_function_{name}": int(overloaded),
            f"medium_latency_function_{name}": int(latency),
        }
        return row, success, bool(overloaded)

    @staticmethod
    def _empty_function_row(name: str) -> dict[str, Any]:
        return {
            f"function_{name}": "",
            f"rate_function_{name}": "",
            f"success_rate_function_{name}": "",
            f"cpu_usage_function_{name}": "",
            f"ram_usage_function_{name}": "",
            f"power_usage_function_{name}": "",
            f"replica_{name}": "",
            f"overloaded_function_{name}": "",
            f"medium_latency_function_{name}": "",
        }

    @staticmethod
    def _extract_node_metrics(
        metrics: dict[str, Any],
    ) -> tuple[float, float, float, float]:
        node_cpu = float(metrics.get("cpu_usage_node", float("nan")))
        node_ram = float(metrics.get("ram_usage_node", float("nan")))
        node_ram_pct = float(metrics.get("ram_usage_node_pct", float("nan")))
        node_power = float(metrics.get("power_usage_node", float("nan")))
        return node_cpu, node_ram, node_ram_pct, node_power

    def _is_node_overloaded(
        self,
        avg_success_rate: float,
        node_cpu: float,
        node_ram_pct: float,
        overloaded_any: bool,
    ) -> int:
        return int(
            avg_success_rate < self.overload.success_rate_node_min
            or node_cpu > self.overload.cpu_overload_pct_of_capacity
            or node_ram_pct > self.overload.ram_overload_pct
            or overloaded_any
        )

    def _build_node_rows(
        self,
        idle_snapshot: MetricsSnapshot,
        node_cpu: float,
        node_ram: float,
        node_ram_pct: float,
        node_power: float,
        rest_seconds: int,
        overloaded_node: int,
    ) -> dict[str, Any]:
        return {
            "cpu_usage_idle_node": self._format_float(idle_snapshot.cpu),
            "cpu_usage_node": self._format_float(node_cpu),
            "ram_usage_idle_node": self._format_float(idle_snapshot.ram),
            "ram_usage_node": self._format_float(node_ram),
            "ram_usage_idle_node_percentage": self._format_float(
                idle_snapshot.ram_pct
            ),
            "ram_usage_node_percentage": self._format_float(node_ram_pct),
            "power_usage_idle_node": self._format_float(idle_snapshot.power),
            "power_usage_node": self._format_float(node_power),
            "rest_seconds": rest_seconds,
            "overloaded_node": overloaded_node,
        }

    @staticmethod
    def _format_float(value: float) -> str:
        if math.isnan(value):
            return "nan"
        return f"{value:.3f}"
