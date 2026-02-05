"""Metrics collector service for DFaaS plugin."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..queries import (
    PrometheusQueryError,
    PrometheusQueryRunner,
    QueryDefinition,
    filter_queries,
    load_queries,
)
from .cooldown import MetricsSnapshot

logger = logging.getLogger(__name__)


@dataclass
class FunctionMetrics:
    """Metrics for a single function."""

    cpu: float
    ram: float
    power: float


@dataclass
class NodeMetrics:
    """Full node metrics including per-function data."""

    cpu: float
    ram: float
    ram_pct: float
    power: float
    functions: dict[str, FunctionMetrics]


class MetricsCollector:
    """Service for collecting metrics from Prometheus.

    Handles:
    - Query loading and filtering
    - Node-level metrics collection
    - Per-function metrics collection
    - Error handling for failed queries
    """

    def __init__(
        self,
        prometheus_url: str,
        queries_path: str | Path,
        duration: str,
        scaphandre_enabled: bool = False,
        function_pid_regexes: dict[str, str] | None = None,
    ) -> None:
        """Initialize MetricsCollector.

        Args:
            prometheus_url: Prometheus server URL
            queries_path: Path to queries YAML file
            duration: Default time span for queries (e.g., "30s")
            scaphandre_enabled: Enable power metrics collection
            function_pid_regexes: Map of function name to PID regex for power queries
        """
        self.prometheus_url = prometheus_url
        self.duration = duration
        self.scaphandre_enabled = scaphandre_enabled
        self.function_pid_regexes = function_pid_regexes or {}

        self._runner = PrometheusQueryRunner(prometheus_url)
        self._queries = self._load_queries(Path(queries_path))
        self._validate_required_queries(self._queries, Path(queries_path))

    def _load_queries(self, queries_path: Path) -> dict[str, QueryDefinition]:
        """Load and filter queries from YAML file."""
        queries = load_queries(queries_path)
        active_queries = filter_queries(
            queries, scaphandre_enabled=self.scaphandre_enabled
        )
        return {query.name: query for query in active_queries}

    def _validate_required_queries(
        self, queries: dict[str, QueryDefinition], queries_path: Path
    ) -> None:
        required = {
            "cpu_usage_node",
            "ram_usage_node",
            "ram_usage_node_pct",
            "cpu_usage_function",
            "ram_usage_function",
        }
        if self.scaphandre_enabled:
            required.update({"power_usage_node", "power_usage_function"})
        missing = sorted(name for name in required if name not in queries)
        if missing:
            joined = ", ".join(missing)
            raise ValueError(
                f"Missing required Prometheus queries in {queries_path}: {joined}"
            )

    def get_node_snapshot(
        self,
        start_time: float | None = None,
        end_time: float | None = None,
    ) -> MetricsSnapshot:
        """Get current node metrics snapshot.

        Args:
            start_time: Optional start time for range query
            end_time: Optional end time for range query

        Returns:
            MetricsSnapshot with CPU, RAM, and power metrics
        """
        cpu = self._runner.execute(
            self._queries["cpu_usage_node"],
            time_span=self.duration,
            start_time=start_time,
            end_time=end_time,
        )
        ram = self._runner.execute(
            self._queries["ram_usage_node"],
            time_span=self.duration,
            start_time=start_time,
            end_time=end_time,
        )
        ram_pct = self._runner.execute(
            self._queries["ram_usage_node_pct"],
            time_span=self.duration,
            start_time=start_time,
            end_time=end_time,
        )
        power = float("nan")
        if self.scaphandre_enabled and "power_usage_node" in self._queries:
            power = self._runner.execute(
                self._queries["power_usage_node"],
                time_span=self.duration,
                start_time=start_time,
                end_time=end_time,
            )
        return MetricsSnapshot(cpu=cpu, ram=ram, ram_pct=ram_pct, power=power)

    def get_function_metrics(
        self,
        function_name: str,
        start_time: float | None = None,
        end_time: float | None = None,
    ) -> FunctionMetrics:
        """Get metrics for a specific function.

        Args:
            function_name: Name of the function
            start_time: Optional start time for range query
            end_time: Optional end time for range query

        Returns:
            FunctionMetrics with CPU, RAM, and power values
        """
        try:
            cpu = self._runner.execute(
                self._queries["cpu_usage_function"],
                time_span=self.duration,
                start_time=start_time,
                end_time=end_time,
                function_name=function_name,
            )
            ram = self._runner.execute(
                self._queries["ram_usage_function"],
                time_span=self.duration,
                start_time=start_time,
                end_time=end_time,
                function_name=function_name,
            )
            power = float("nan")
            if self.scaphandre_enabled and "power_usage_function" in self._queries:
                pid_regex = self.function_pid_regexes.get(function_name)
                if pid_regex:
                    power = self._runner.execute(
                        self._queries["power_usage_function"],
                        time_span=self.duration,
                        start_time=start_time,
                        end_time=end_time,
                        pid_regex=pid_regex,
                    )
            return FunctionMetrics(cpu=cpu, ram=ram, power=power)
        except PrometheusQueryError as exc:
            logger.warning("Prometheus query failed for %s: %s", function_name, exc)
            return FunctionMetrics(
                cpu=float("nan"), ram=float("nan"), power=float("nan")
            )

    def collect_all_metrics(
        self,
        function_names: list[str],
        start_time: float,
        end_time: float,
        duration_seconds: int,
    ) -> dict[str, Any]:
        """Collect all metrics for a benchmark run.

        Args:
            function_names: List of function names to query
            start_time: Start time of the benchmark run
            end_time: End time of the benchmark run
            duration_seconds: Duration of the test in seconds

        Returns:
            Dict containing node metrics and per-function metrics
        """
        # Determine if we need range query based on actual vs expected duration
        actual_duration = end_time - start_time
        use_range = actual_duration > duration_seconds
        query_start = start_time if use_range else None
        query_end = end_time if use_range else None

        node = self.get_node_snapshot(query_start, query_end)
        metrics: dict[str, Any] = {
            "cpu_usage_node": node.cpu,
            "ram_usage_node": node.ram,
            "ram_usage_node_pct": node.ram_pct,
            "power_usage_node": node.power,
            "functions": {},
        }

        for name in function_names:
            fn_metrics = self.get_function_metrics(name, query_start, query_end)
            metrics["functions"][name] = {
                "cpu": fn_metrics.cpu,
                "ram": fn_metrics.ram,
                "power": fn_metrics.power,
            }

        return metrics
