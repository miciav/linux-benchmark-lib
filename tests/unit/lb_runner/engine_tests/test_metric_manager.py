"""Unit tests for MetricManager."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import logging

import pytest

from lb_runner.engine.metrics import MetricManager


pytestmark = [pytest.mark.unit, pytest.mark.unit_runner]


@pytest.fixture
def mock_registry():
    """Create a mock plugin registry."""
    return MagicMock()


@pytest.fixture
def mock_output_manager():
    """Create a mock output manager."""
    return MagicMock()


@pytest.fixture
def metric_manager(mock_registry, mock_output_manager):
    """Create a MetricManager instance for testing."""
    return MetricManager(
        registry=mock_registry,
        output_manager=mock_output_manager,
        host_name="test-host",
    )


class TestMetricManagerInit:
    """Tests for MetricManager initialization."""

    def test_creates_with_dependencies(
        self, mock_registry, mock_output_manager
    ) -> None:
        """MetricManager initializes with registry and output manager."""
        mgr = MetricManager(
            registry=mock_registry,
            output_manager=mock_output_manager,
            host_name="node-1",
        )
        assert mgr._host_name == "node-1"
        assert mgr.system_info is None


class TestMetricManagerCollectors:
    """Tests for collector management."""

    def test_create_collectors_delegates_to_coordinator(
        self, metric_manager, mock_registry
    ) -> None:
        """create_collectors should delegate to the coordinator."""
        config = MagicMock()
        collectors = [MagicMock(), MagicMock()]
        metric_manager._coordinator.create_collectors = MagicMock(
            return_value=collectors
        )

        result = metric_manager.create_collectors(config)

        metric_manager._coordinator.create_collectors.assert_called_once_with(config)
        assert result == collectors

    def test_start_collectors_delegates_to_coordinator(
        self, metric_manager
    ) -> None:
        """start_collectors should delegate to the coordinator."""
        collectors = [MagicMock(), MagicMock()]
        metric_manager._coordinator.start = MagicMock()

        metric_manager.start_collectors(collectors)

        metric_manager._coordinator.start.assert_called_once()
        assert metric_manager._coordinator.start.call_args[0][0] == collectors

    def test_stop_collectors_delegates_to_coordinator(
        self, metric_manager
    ) -> None:
        """stop_collectors should delegate to the coordinator."""
        collectors = [MagicMock(), MagicMock()]
        metric_manager._coordinator.stop = MagicMock()

        metric_manager.stop_collectors(collectors)

        metric_manager._coordinator.stop.assert_called_once()
        assert metric_manager._coordinator.stop.call_args[0][0] == collectors


class TestMetricManagerCollectMetrics:
    """Tests for collect_metrics method."""

    def test_collect_metrics_delegates_to_coordinator(
        self, metric_manager, tmp_path
    ) -> None:
        """collect_metrics should delegate to the coordinator."""
        collectors = [MagicMock()]
        workload_dir = tmp_path / "workload"
        rep_dir = workload_dir / "rep1"
        result = {"metrics": {}}
        metric_manager._coordinator.collect = MagicMock()

        metric_manager.collect_metrics(
            collectors, workload_dir, rep_dir, "test-workload", 1, result
        )

        metric_manager._coordinator.collect.assert_called_once_with(
            collectors, workload_dir, rep_dir, "test-workload", 1, result
        )


class TestMetricManagerSystemInfo:
    """Tests for system info collection."""

    def test_collect_system_info_stores_result(
        self, metric_manager, mock_output_manager
    ) -> None:
        """collect_system_info should store the result."""
        mock_info = MagicMock()
        mock_info.to_dict.return_value = {"host": "test", "os": "linux"}

        with patch(
            "lb_runner.engine.metrics.system_info.collect_system_info",
            return_value=mock_info,
        ):
            result = metric_manager.collect_system_info()

        assert result == {"host": "test", "os": "linux"}
        assert metric_manager.system_info == {"host": "test", "os": "linux"}

    def test_collect_system_info_writes_to_output(
        self, metric_manager, mock_output_manager
    ) -> None:
        """collect_system_info should write to output manager."""
        mock_info = MagicMock()
        mock_info.to_dict.return_value = {}

        with patch(
            "lb_runner.engine.metrics.system_info.collect_system_info",
            return_value=mock_info,
        ):
            metric_manager.collect_system_info()

        mock_output_manager.write_system_info.assert_called_once_with(mock_info)


class TestMetricManagerEventLogger:
    """Tests for event logger attachment."""

    def test_attach_event_logger_returns_handler(self, metric_manager) -> None:
        """attach_event_logger should return a handler."""
        with patch.dict("os.environ", {"LB_ENABLE_EVENT_LOGGING": "1"}):
            handler = metric_manager.attach_event_logger(
                test_name="workload",
                repetition=1,
                total_repetitions=3,
                current_run_id="run-1",
            )

        assert handler is not None
        # Clean up
        logging.getLogger().removeHandler(handler)

    def test_attach_event_logger_disabled_returns_none(self, metric_manager) -> None:
        """attach_event_logger returns None when disabled."""
        with patch.dict("os.environ", {"LB_ENABLE_EVENT_LOGGING": "0"}):
            handler = metric_manager.attach_event_logger(
                test_name="workload",
                repetition=1,
                total_repetitions=3,
                current_run_id="run-1",
            )

        assert handler is None

    def test_detach_event_logger_removes_handler(self, metric_manager) -> None:
        """detach_event_logger should remove the handler."""
        handler = MagicMock()
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)

        MetricManager.detach_event_logger(handler)

        assert handler not in root_logger.handlers

    def test_detach_event_logger_handles_none(self, metric_manager) -> None:
        """detach_event_logger should handle None gracefully."""
        # Should not raise
        MetricManager.detach_event_logger(None)
