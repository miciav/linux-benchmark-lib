"""Unit tests for BenchmarkController stop protocol integration."""

from pathlib import Path
from unittest.mock import MagicMock, ANY, patch

import pytest
from lb_controller.engine.controller import BenchmarkController
from lb_controller.engine.stops import StopState
from lb_controller.models.types import ExecutionResult
from lb_runner.models.config import BenchmarkConfig, RemoteHostConfig
from lb_runner.engine.stop_token import StopToken


@pytest.fixture
def mock_executor():
    executor = MagicMock()
    executor.run_playbook.return_value = ExecutionResult(rc=0, status="ok")
    return executor


@pytest.fixture
def controller(mock_executor):
    config = BenchmarkConfig(
        remote_hosts=[RemoteHostConfig(name="node1", address="1.2.3.4")],
        output_dir=Path("/tmp/out"),
        report_dir=Path("/tmp/rep"),
        data_export_dir=Path("/tmp/exp"),
    )
    stop_token = StopToken(enable_signals=False)
    ctrl = BenchmarkController(config, executor=mock_executor, stop_token=stop_token)
    # Mock coordinator to avoid real timing logic
    ctrl.coordinator = MagicMock()
    ctrl.coordinator.state = StopState.IDLE
    return ctrl


def test_handle_stop_protocol_success(controller, mock_executor):
    """Test successful execution of the stop protocol."""
    # Setup mocks
    controller.coordinator.state = StopState.TEARDOWN_READY
    
    # Call the method
    log_fn = MagicMock()
    inventory = MagicMock()
    extravars = {}
    
    result = controller._handle_stop_protocol(inventory, extravars, log_fn)

    # Verify result
    assert result is True
    
    # Verify initiation
    controller.coordinator.initiate_stop.assert_called_once()
    
    # Verify stop playbook execution
    # The second call to run_playbook should be the stop playbook (or first if we just call the method directly)
    mock_executor.run_playbook.assert_called()
    call_args = mock_executor.run_playbook.call_args
    assert call_args.kwargs.get("cancellable") is False
    assert "lb-stop-protocol" in str(call_args.args[0])  # Temp file path
    
    # Verify logging
    log_fn.assert_any_call("Stop confirmed; initiating distributed stop protocol...")
    log_fn.assert_any_call("All runners confirmed stop.")


def test_handle_stop_protocol_failure(controller, mock_executor):
    """Test failure (timeout) of the stop protocol."""
    # Setup mocks
    # We need to simulate the loop checking. 
    # The loop checks state. We'll set it to STOP_FAILED immediately.
    controller.coordinator.state = StopState.STOP_FAILED
    
    log_fn = MagicMock()
    
    result = controller._handle_stop_protocol(MagicMock(), {}, log_fn)
    
    assert result is False
    log_fn.assert_any_call("Stop protocol timed out or failed.")


@patch("time.sleep", return_value=None)  # Avoid waiting
def test_handle_stop_protocol_waits_for_state(_mock_sleep, controller, mock_executor):
    """Test that the controller waits for the coordinator state to change."""
    
    # Side effect for state property to simulate transition: IDLE -> STOPPING -> TEARDOWN_READY
    # But checking .state is an attribute access, not a call.
    # We can use a property mock or just update it in a side effect of check_timeout
    
    states = [StopState.STOPPING_WORKLOADS, StopState.STOPPING_WORKLOADS, StopState.TEARDOWN_READY]
    
    def side_effect_check():
        if states:
            controller.coordinator.state = states.pop(0)
            
    controller.coordinator.check_timeout.side_effect = side_effect_check
    controller.coordinator.state = StopState.STOPPING_WORKLOADS # Initial
    
    result = controller._handle_stop_protocol(MagicMock(), {}, MagicMock())
    
    assert result is True
    assert controller.coordinator.check_timeout.call_count >= 1


def test_handle_stop_protocol_playbook_failure(controller, mock_executor):
    """Test behavior when the stop playbook fails to run."""
    mock_executor.run_playbook.return_value = ExecutionResult(rc=1, status="failed")
    controller.coordinator.state = StopState.TEARDOWN_READY # Assume it works anyway?
    
    log_fn = MagicMock()
    result = controller._handle_stop_protocol(MagicMock(), {}, log_fn)
    
    # It should still proceed to wait
    assert result is True
    log_fn.assert_any_call("Failed to send stop signal (playbook failure).")
