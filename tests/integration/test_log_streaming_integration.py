"""Integration tests for log streaming in LocalRunner."""

from unittest.mock import MagicMock, patch

import pytest

from lb_runner.api import BenchmarkConfig, LBEventLogHandler, LocalRunner, RunnerRegistry


@pytest.mark.inter_generic
def test_local_runner_attaches_log_handler(monkeypatch, tmp_path):
    """Verify LocalRunner attaches LBEventLogHandler when env var is set."""
    # Mock environment
    monkeypatch.setenv("LB_ENABLE_EVENT_LOGGING", "1")
    
    mock_config = BenchmarkConfig(
        output_dir=tmp_path / "out",
        report_dir=tmp_path / "reports",
        data_export_dir=tmp_path / "exports",
        workloads={},
        warmup_seconds=0,
        test_duration_seconds=1,
        cooldown_seconds=0,
        collect_system_info=False,
    )

    mock_registry = MagicMock(spec=RunnerRegistry)
    mock_registry.create_collectors.return_value = []
    mock_registry.create_generator.return_value = MagicMock()

    runner = LocalRunner(mock_config, mock_registry)
    
    # We want to spy on logging.getLogger().addHandler/removeHandler
    with patch("logging.getLogger") as mock_get_logger:
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger
        
        handler = runner._metric_manager.attach_event_logger(
            "test_workload", 1, 1, "run-1"
        )
        
        # Verify addHandler was called with an LBEventLogHandler
        mock_logger.addHandler.assert_called_once()
        handler_arg = mock_logger.addHandler.call_args[0][0]
        assert isinstance(handler_arg, LBEventLogHandler)
        assert handler_arg.workload == "test_workload"
        
        # Verify removeHandler was called
        runner._metric_manager.detach_event_logger(handler)
        mock_logger.removeHandler.assert_called_with(handler_arg)


@pytest.mark.inter_generic
def test_local_runner_ignores_log_handler_when_disabled(monkeypatch, tmp_path):
    """Verify LocalRunner does NOT attach handler if env var disables it."""
    monkeypatch.setenv("LB_ENABLE_EVENT_LOGGING", "0")
    
    mock_config = BenchmarkConfig(
        output_dir=tmp_path / "out",
        report_dir=tmp_path / "reports",
        data_export_dir=tmp_path / "exports",
        workloads={},
        warmup_seconds=0,
        test_duration_seconds=1,
        cooldown_seconds=0,
        collect_system_info=False,
    )
    mock_registry = MagicMock(spec=RunnerRegistry)
    mock_registry.create_collectors.return_value = []
    mock_registry.create_generator.return_value = MagicMock()

    runner = LocalRunner(mock_config, mock_registry)
    
    with patch("logging.getLogger") as mock_get_logger:
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger
        
        handler = runner._metric_manager.attach_event_logger(
            "test_workload", 1, 1, "run-1"
        )
        
        # Verify addHandler was NOT called with LBEventLogHandler
        assert handler is None
        mock_logger.addHandler.assert_not_called()
