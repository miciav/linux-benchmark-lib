"""Integration tests for log streaming in LocalRunner."""

from unittest.mock import MagicMock, patch

import pytest

from lb_runner.api import BenchmarkConfig, LBEventLogHandler, LocalRunner, RunnerRegistry


@pytest.mark.inter_generic
def test_local_runner_attaches_log_handler(monkeypatch):
    """Verify LocalRunner attaches LBEventLogHandler when env var is set."""
    # Mock environment
    monkeypatch.setenv("LB_ENABLE_EVENT_LOGGING", "1")
    
    # Mock dependencies
    mock_config = MagicMock(spec=BenchmarkConfig)
    mock_config.output_dir = MagicMock()
    mock_config.warmup_seconds = 0
    mock_config.test_duration_seconds = 0
    mock_config.cooldown_seconds = 0
    
    mock_registry = MagicMock(spec=RunnerRegistry)
    mock_generator = MagicMock()
    # Mock generator behavior
    mock_generator.get_result.return_value = {"returncode": 0}
    mock_generator._is_running = False # Stop immediately
    mock_registry.create_collectors.return_value = []
    mock_registry.create_generator.return_value = mock_generator
    
    runner = LocalRunner(mock_config, mock_registry)
    
    # We need to mock _workload_output_dir or it will try to create dirs
    runner._workload_output_dir = MagicMock()
    runner._pre_test_cleanup = MagicMock()
    runner._emit_progress = MagicMock()
    
    # We want to spy on logging.getLogger().addHandler/removeHandler
    with patch("logging.getLogger") as mock_get_logger:
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger
        
        runner._run_single_test("test_workload", mock_generator, 1, 1)
        
        # Verify addHandler was called with an LBEventLogHandler
        add_calls = mock_logger.addHandler.call_args_list
        assert len(add_calls) > 0
        handler_arg = add_calls[0][0][0]
        assert isinstance(handler_arg, LBEventLogHandler)
        assert handler_arg.workload == "test_workload"
        
        # Verify removeHandler was called
        mock_logger.removeHandler.assert_called_with(handler_arg)


@pytest.mark.inter_generic
def test_local_runner_ignores_log_handler_when_disabled(monkeypatch):
    """Verify LocalRunner does NOT attach handler if env var disables it."""
    monkeypatch.setenv("LB_ENABLE_EVENT_LOGGING", "0")
    
    mock_config = MagicMock(spec=BenchmarkConfig)
    mock_config.warmup_seconds = 0
    mock_config.test_duration_seconds = 0
    mock_registry = MagicMock(spec=RunnerRegistry)
    mock_generator = MagicMock()
    mock_generator.get_result.return_value = 0
    mock_registry.create_collectors.return_value = []
    mock_registry.create_generator.return_value = mock_generator
    
    runner = LocalRunner(mock_config, mock_registry)
    runner._workload_output_dir = MagicMock()
    runner._pre_test_cleanup = MagicMock()
    runner._emit_progress = MagicMock()
    
    with patch("logging.getLogger") as mock_get_logger:
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger
        
        runner._run_single_test("test_workload", mock_generator, 1, 1)
        
        # Verify addHandler was NOT called with LBEventLogHandler
        for call in mock_logger.addHandler.call_args_list:
            arg = call[0][0]
            assert not isinstance(arg, LBEventLogHandler)
