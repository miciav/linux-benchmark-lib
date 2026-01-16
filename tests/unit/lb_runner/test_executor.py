"""Unit tests for RepetitionExecutor."""

import logging
from unittest.mock import MagicMock, call, patch
import pytest
from datetime import datetime

from lb_runner.engine.executor import RepetitionExecutor
from lb_runner.engine.execution import StopRequested
from lb_runner.engine.context import RunnerContext

@pytest.fixture
def mock_config():
    config = MagicMock()
    config.warmup_seconds = 0
    config.output_dir = "dummy_output"
    return config

@pytest.fixture
def mock_metric_manager():
    return MagicMock()

@pytest.fixture
def mock_output_manager():
    return MagicMock()

@pytest.fixture
def mock_log_manager():
    return MagicMock()

@pytest.fixture
def context(mock_config, mock_metric_manager, mock_output_manager, mock_log_manager):
    return RunnerContext(
        run_id="run-1",
        config=mock_config,
        output_manager=mock_output_manager,
        log_manager=mock_log_manager,
        metric_manager=mock_metric_manager,
    )

@pytest.fixture
def executor(context):
    return RepetitionExecutor(context)

def test_execute_success(executor, context):
    """Test successful execution of a test repetition."""
    generator = MagicMock()
    generator.get_result.return_value = {"status": "ok"}
    
    context.metric_manager.create_collectors.return_value = ["collector1"]
    context.output_manager.workload_output_dir.return_value = MagicMock()
    
    # Mock resolve_duration
    with patch("lb_runner.engine.executor.resolve_duration", return_value=1):
        with patch("lb_runner.engine.executor.wait_for_generator", return_value=datetime.now()):
             result = executor.execute("test_workload", generator, 1, 3)

    assert result["generator_result"] == {"status": "ok"}
    assert generator.start.called
    assert context.metric_manager.start_collectors.called
    assert context.metric_manager.stop_collectors.called
    assert context.metric_manager.collect_metrics.called
    assert context.output_manager.persist_rep_result.called

def test_execute_stop_requested(executor, context):
    """Test execution when stop is requested."""
    generator = MagicMock()
    stop_token = MagicMock()
    stop_token.should_stop.return_value = True
    context.stop_token = stop_token
    
    # Mock resolve_duration
    with patch("lb_runner.engine.executor.resolve_duration", return_value=1):
         with pytest.raises(StopRequested):
             executor.execute("test_workload", generator, 1, 3)

    assert not generator.start.called
    # Cleanup should still be called
    assert context.metric_manager.stop_collectors.called

def test_execute_generator_failure(executor, context):
    """Test execution when generator fails."""
    generator = MagicMock()
    generator.start.side_effect = RuntimeError("Generator crashed")
    
    with patch("lb_runner.engine.executor.resolve_duration", return_value=1):
        with pytest.raises(RuntimeError):
             executor.execute("test_workload", generator, 1, 3)

    assert context.metric_manager.stop_collectors.called