"""Unit tests for DFaaS MetricsCollector service."""

from __future__ import annotations

import math
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lb_plugins.plugins.dfaas.services.metrics_collector import (
    FunctionMetrics,
    MetricsCollector,
    NodeMetrics,
)
from lb_plugins.plugins.dfaas.services.cooldown import MetricsSnapshot
from lb_plugins.plugins.dfaas.queries import PrometheusQueryError

pytestmark = [pytest.mark.unit_plugins]


@pytest.fixture
def queries_path(tmp_path: Path) -> Path:
    """Create a temporary queries YAML file."""
    queries_file = tmp_path / "queries.yml"
    queries_file.write_text(
        """
queries:
  - name: cpu_usage_node
    query: "avg(rate(node_cpu_seconds_total{mode!='idle'}[{duration}]))*100"
  - name: ram_usage_node
    query: "node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes"
  - name: ram_usage_node_pct
    query: "(1 - node_memory_MemAvailable_bytes/node_memory_MemTotal_bytes)*100"
  - name: cpu_usage_function
    query: "sum(rate(container_cpu_usage_seconds_total{container='{function_name}'}[{duration}]))*100"
  - name: ram_usage_function
    query: "sum(container_memory_usage_bytes{container='{function_name}'})"
  - name: power_usage_node
    query: "avg(scaph_host_power_microwatts)/1000000"
    enabled_if: scaphandre
  - name: power_usage_function
    query: "sum(scaph_process_power_consumption_microwatts{cmdline=~'{pid_regex}'})/1000000"
    enabled_if: scaphandre
"""
    )
    return queries_file


class TestMetricsCollectorInit:
    def test_initializes_with_valid_config(self, queries_path: Path) -> None:
        with patch(
            "lb_plugins.plugins.dfaas.services.metrics_collector.PrometheusQueryRunner"
        ):
            collector = MetricsCollector(
                prometheus_url="http://localhost:9090",
                queries_path=queries_path,
                duration="30s",
                scaphandre_enabled=False,
            )
            assert collector.prometheus_url == "http://localhost:9090"
            assert collector.duration == "30s"
            assert collector.scaphandre_enabled is False

    def test_loads_queries_from_path(self, queries_path: Path) -> None:
        with patch(
            "lb_plugins.plugins.dfaas.services.metrics_collector.PrometheusQueryRunner"
        ):
            collector = MetricsCollector(
                prometheus_url="http://localhost:9090",
                queries_path=queries_path,
                duration="30s",
                scaphandre_enabled=False,
            )
            assert "cpu_usage_node" in collector._queries
            assert "ram_usage_node" in collector._queries
            assert "power_usage_node" not in collector._queries  # scaphandre disabled

    def test_loads_power_queries_when_scaphandre_enabled(
        self, queries_path: Path
    ) -> None:
        with patch(
            "lb_plugins.plugins.dfaas.services.metrics_collector.PrometheusQueryRunner"
        ):
            collector = MetricsCollector(
                prometheus_url="http://localhost:9090",
                queries_path=queries_path,
                duration="30s",
                scaphandre_enabled=True,
            )
            assert "power_usage_node" in collector._queries
            assert "power_usage_function" in collector._queries

    def test_missing_required_queries_raises(self, tmp_path: Path) -> None:
        queries_file = tmp_path / "queries.yml"
        queries_file.write_text(
            """
queries:
  - name: cpu_usage_node
    query: "avg(rate(node_cpu_seconds_total{mode!='idle'}[{time_span}]))*100"
"""
        )
        with patch(
            "lb_plugins.plugins.dfaas.services.metrics_collector.PrometheusQueryRunner"
        ):
            with pytest.raises(ValueError, match="Missing required Prometheus queries"):
                MetricsCollector(
                    prometheus_url="http://localhost:9090",
                    queries_path=queries_file,
                    duration="30s",
                    scaphandre_enabled=False,
                )

    def test_missing_power_queries_raises_when_scaphandre_enabled(
        self, tmp_path: Path
    ) -> None:
        queries_file = tmp_path / "queries.yml"
        queries_file.write_text(
            """
queries:
  - name: cpu_usage_node
    query: "avg(rate(node_cpu_seconds_total{mode!='idle'}[{time_span}]))*100"
  - name: ram_usage_node
    query: "node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes"
  - name: ram_usage_node_pct
    query: "(1 - node_memory_MemAvailable_bytes/node_memory_MemTotal_bytes)*100"
  - name: cpu_usage_function
    query: "sum(rate(container_cpu_usage_seconds_total{container='{function_name}'}[{time_span}]))*100"
  - name: ram_usage_function
    query: "sum(container_memory_usage_bytes{container='{function_name}'})"
"""
        )
        with patch(
            "lb_plugins.plugins.dfaas.services.metrics_collector.PrometheusQueryRunner"
        ):
            with pytest.raises(ValueError, match="Missing required Prometheus queries"):
                MetricsCollector(
                    prometheus_url="http://localhost:9090",
                    queries_path=queries_file,
                    duration="30s",
                    scaphandre_enabled=True,
                )


class TestGetNodeSnapshot:
    def test_returns_metrics_snapshot(self, queries_path: Path) -> None:
        mock_runner = MagicMock()
        mock_runner.execute.side_effect = [10.5, 2048.0, 45.0]  # cpu, ram, ram_pct

        with patch(
            "lb_plugins.plugins.dfaas.services.metrics_collector.PrometheusQueryRunner",
            return_value=mock_runner,
        ):
            collector = MetricsCollector(
                prometheus_url="http://localhost:9090",
                queries_path=queries_path,
                duration="30s",
                scaphandre_enabled=False,
            )
            snapshot = collector.get_node_snapshot()

            assert isinstance(snapshot, MetricsSnapshot)
            assert snapshot.cpu == 10.5
            assert snapshot.ram == 2048.0
            assert snapshot.ram_pct == 45.0
            assert math.isnan(snapshot.power)

    def test_includes_power_when_scaphandre_enabled(self, queries_path: Path) -> None:
        mock_runner = MagicMock()
        mock_runner.execute.side_effect = [
            10.5,
            2048.0,
            45.0,
            150.0,
        ]  # cpu, ram, ram_pct, power

        with patch(
            "lb_plugins.plugins.dfaas.services.metrics_collector.PrometheusQueryRunner",
            return_value=mock_runner,
        ):
            collector = MetricsCollector(
                prometheus_url="http://localhost:9090",
                queries_path=queries_path,
                duration="30s",
                scaphandre_enabled=True,
            )
            snapshot = collector.get_node_snapshot()

            assert snapshot.power == 150.0

    def test_passes_time_range_to_runner(self, queries_path: Path) -> None:
        mock_runner = MagicMock()
        mock_runner.execute.return_value = 0.0

        with patch(
            "lb_plugins.plugins.dfaas.services.metrics_collector.PrometheusQueryRunner",
            return_value=mock_runner,
        ):
            collector = MetricsCollector(
                prometheus_url="http://localhost:9090",
                queries_path=queries_path,
                duration="30s",
                scaphandre_enabled=False,
            )
            collector.get_node_snapshot(start_time=1000.0, end_time=1030.0)

            call_args = mock_runner.execute.call_args_list[0]
            assert call_args.kwargs["start_time"] == 1000.0
            assert call_args.kwargs["end_time"] == 1030.0


class TestGetFunctionMetrics:
    def test_returns_function_metrics(self, queries_path: Path) -> None:
        mock_runner = MagicMock()
        mock_runner.execute.side_effect = [5.0, 512.0]  # cpu, ram

        with patch(
            "lb_plugins.plugins.dfaas.services.metrics_collector.PrometheusQueryRunner",
            return_value=mock_runner,
        ):
            collector = MetricsCollector(
                prometheus_url="http://localhost:9090",
                queries_path=queries_path,
                duration="30s",
                scaphandre_enabled=False,
            )
            metrics = collector.get_function_metrics("my-function")

            assert isinstance(metrics, FunctionMetrics)
            assert metrics.cpu == 5.0
            assert metrics.ram == 512.0
            assert math.isnan(metrics.power)

    def test_includes_power_with_pid_regex(self, queries_path: Path) -> None:
        mock_runner = MagicMock()
        mock_runner.execute.side_effect = [5.0, 512.0, 25.0]  # cpu, ram, power

        with patch(
            "lb_plugins.plugins.dfaas.services.metrics_collector.PrometheusQueryRunner",
            return_value=mock_runner,
        ):
            collector = MetricsCollector(
                prometheus_url="http://localhost:9090",
                queries_path=queries_path,
                duration="30s",
                scaphandre_enabled=True,
                function_pid_regexes={"my-function": ".*my-function.*"},
            )
            metrics = collector.get_function_metrics("my-function")

            assert metrics.power == 25.0

    def test_handles_query_error_gracefully(self, queries_path: Path) -> None:
        mock_runner = MagicMock()
        mock_runner.execute.side_effect = PrometheusQueryError("Connection failed")

        with patch(
            "lb_plugins.plugins.dfaas.services.metrics_collector.PrometheusQueryRunner",
            return_value=mock_runner,
        ):
            collector = MetricsCollector(
                prometheus_url="http://localhost:9090",
                queries_path=queries_path,
                duration="30s",
                scaphandre_enabled=False,
            )
            metrics = collector.get_function_metrics("my-function")

            assert math.isnan(metrics.cpu)
            assert math.isnan(metrics.ram)
            assert math.isnan(metrics.power)


class TestCollectAllMetrics:
    def test_collects_node_and_function_metrics(self, queries_path: Path) -> None:
        mock_runner = MagicMock()
        # First call: node metrics (cpu, ram, ram_pct)
        # Then: function1 (cpu, ram), function2 (cpu, ram)
        mock_runner.execute.side_effect = [
            10.0,
            2048.0,
            50.0,  # node
            3.0,
            256.0,  # func1
            4.0,
            384.0,  # func2
        ]

        with patch(
            "lb_plugins.plugins.dfaas.services.metrics_collector.PrometheusQueryRunner",
            return_value=mock_runner,
        ):
            collector = MetricsCollector(
                prometheus_url="http://localhost:9090",
                queries_path=queries_path,
                duration="30s",
                scaphandre_enabled=False,
            )
            metrics = collector.collect_all_metrics(
                ["func1", "func2"],
                start_time=1000.0,
                end_time=1030.0,
                duration_seconds=30,
            )

            assert metrics["cpu_usage_node"] == 10.0
            assert metrics["ram_usage_node"] == 2048.0
            assert metrics["functions"]["func1"]["cpu"] == 3.0
            assert metrics["functions"]["func2"]["ram"] == 384.0

    def test_uses_range_query_when_duration_exceeds_expected(
        self, queries_path: Path
    ) -> None:
        mock_runner = MagicMock()
        mock_runner.execute.return_value = 0.0

        with patch(
            "lb_plugins.plugins.dfaas.services.metrics_collector.PrometheusQueryRunner",
            return_value=mock_runner,
        ):
            collector = MetricsCollector(
                prometheus_url="http://localhost:9090",
                queries_path=queries_path,
                duration="30s",
                scaphandre_enabled=False,
            )
            collector.collect_all_metrics(
                ["func1"],
                start_time=1000.0,
                end_time=1060.0,  # 60 seconds > 30 seconds duration
                duration_seconds=30,
            )

            # Node snapshot call should have time range
            call_args = mock_runner.execute.call_args_list[0]
            assert call_args.kwargs["start_time"] == 1000.0
            assert call_args.kwargs["end_time"] == 1060.0

    def test_uses_instant_query_when_duration_within_expected(
        self, queries_path: Path
    ) -> None:
        mock_runner = MagicMock()
        mock_runner.execute.return_value = 0.0

        with patch(
            "lb_plugins.plugins.dfaas.services.metrics_collector.PrometheusQueryRunner",
            return_value=mock_runner,
        ):
            collector = MetricsCollector(
                prometheus_url="http://localhost:9090",
                queries_path=queries_path,
                duration="30s",
                scaphandre_enabled=False,
            )
            collector.collect_all_metrics(
                ["func1"],
                start_time=1000.0,
                end_time=1025.0,  # 25 seconds <= 30 seconds duration
                duration_seconds=30,
            )

            # Node snapshot call should have no time range
            call_args = mock_runner.execute.call_args_list[0]
            assert call_args.kwargs["start_time"] is None
            assert call_args.kwargs["end_time"] is None


class TestDataClasses:
    def test_function_metrics_values(self) -> None:
        metrics = FunctionMetrics(cpu=5.5, ram=1024.0, power=10.0)
        assert metrics.cpu == 5.5
        assert metrics.ram == 1024.0
        assert metrics.power == 10.0

    def test_node_metrics_values(self) -> None:
        fn_metrics = {"func1": FunctionMetrics(cpu=1.0, ram=100.0, power=5.0)}
        metrics = NodeMetrics(
            cpu=10.0, ram=2048.0, ram_pct=50.0, power=150.0, functions=fn_metrics
        )
        assert metrics.cpu == 10.0
        assert metrics.functions["func1"].cpu == 1.0
