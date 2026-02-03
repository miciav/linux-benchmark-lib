"""Unit tests for stop protocol logic."""

from unittest.mock import MagicMock, patch

import pytest
from lb_controller.engine.stops import StopState
from lb_controller.models.types import ExecutionResult
from lb_controller.engine.stop_logic import handle_stop_protocol
from lb_controller.services.services import ControllerServices
from lb_controller.engine.session import RunSession


@pytest.fixture
def mock_executor():
    executor = MagicMock()
    executor.run_playbook.return_value = ExecutionResult(rc=0, status="ok")
    return executor


@pytest.fixture
def services(mock_executor):
    lifecycle = MagicMock()
    return ControllerServices(
        config=MagicMock(),
        executor=mock_executor,
        lifecycle=lifecycle
    )

@pytest.fixture
def session():
    sess = MagicMock(spec=RunSession)
    sess.coordinator = MagicMock()
    sess.coordinator.state = StopState.IDLE
    return sess


def test_handle_stop_protocol_success(services, session, mock_executor):
    """Test successful execution of the stop protocol."""
    # Setup mocks
    session.coordinator.state = StopState.TEARDOWN_READY
    
    # Call the method
    log_fn = MagicMock()
    inventory = MagicMock()
    extravars = {}
    
    result = handle_stop_protocol(services, session, inventory, extravars, log_fn)

    # Verify result
    assert result is True
    
    # Verify initiation
    session.coordinator.initiate_stop.assert_called_once()
    
    # Verify stop playbook execution
    mock_executor.run_playbook.assert_called()
    call_args = mock_executor.run_playbook.call_args
    assert call_args.kwargs.get("cancellable") is False
    assert "lb-stop-protocol" in str(call_args.args[0])
    
    # Verify logging
    log_fn.assert_any_call("Stop confirmed; initiating distributed stop protocol...")
    log_fn.assert_any_call("All runners confirmed stop.")


def test_handle_stop_protocol_failure(services, session, mock_executor):
    """Test failure (timeout) of the stop protocol."""
    session.coordinator.state = StopState.STOP_FAILED
    
    log_fn = MagicMock()
    
    result = handle_stop_protocol(services, session, MagicMock(), {}, log_fn)
    
    assert result is False
    log_fn.assert_any_call("Stop protocol timed out or failed.")


@patch("time.sleep", return_value=None)
def test_handle_stop_protocol_waits_for_state(_mock_sleep, services, session, mock_executor):
    """Test that the protocol waits for the coordinator state to change."""
    
    states = [StopState.STOPPING_WORKLOADS, StopState.STOPPING_WORKLOADS, StopState.TEARDOWN_READY]
    
    def side_effect_check():
        if states:
            session.coordinator.state = states.pop(0)
            
    session.coordinator.check_timeout.side_effect = side_effect_check
    session.coordinator.state = StopState.STOPPING_WORKLOADS
    
    result = handle_stop_protocol(services, session, MagicMock(), {}, MagicMock())
    
    assert result is True
    assert session.coordinator.check_timeout.call_count >= 1


def test_handle_stop_protocol_playbook_failure(services, session, mock_executor):
    """Test behavior when the stop playbook fails to run."""
    mock_executor.run_playbook.return_value = ExecutionResult(rc=1, status="failed")
    session.coordinator.state = StopState.TEARDOWN_READY
    
    log_fn = MagicMock()
    result = handle_stop_protocol(services, session, MagicMock(), {}, log_fn)
    
    # It should still proceed to wait
    assert result is True
    log_fn.assert_any_call("Failed to send stop signal (playbook failure).")