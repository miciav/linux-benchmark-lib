"""Unit tests for RunSession."""

from unittest.mock import MagicMock
from lb_controller.engine.session import RunSession
from lb_controller.models.state import ControllerState, ControllerStateMachine


def test_run_session_initialization():
    """Test correct initialization of RunSession."""
    run_state = MagicMock()
    run_state.resolved_run_id = "test-run-1"
    coordinator = MagicMock()
    machine = ControllerStateMachine()

    session = RunSession(run_state, coordinator, machine)

    assert session.state is run_state
    assert session.coordinator is coordinator
    assert session.state_machine is machine
    assert session.run_id == "test-run-1"


def test_run_session_transitions():
    """Test state transitions via RunSession methods."""
    run_state = MagicMock()
    session = RunSession(run_state)

    # Default state is INIT
    assert session.state_machine.state == ControllerState.INIT

    session.transition(ControllerState.RUNNING_GLOBAL_SETUP)
    assert session.state_machine.state == ControllerState.RUNNING_GLOBAL_SETUP

    session.arm_stop(reason="test")
    assert session.state_machine.state == ControllerState.STOP_ARMED


def test_run_session_allows_cleanup():
    """Test delegation of allows_cleanup."""
    run_state = MagicMock()
    session = RunSession(run_state)

    # INIT does not allow cleanup
    assert session.allows_cleanup() is False

    # Transition to FINISHED to allow cleanup
    # Need valid transition path from INIT: INIT -> RUNNING... -> FINISHED
    # Or just jump if allowed, let's check strict transitions
    # INIT -> FINISHED is allowed in _ALLOWED_TRANSITIONS for testing/skipping

    session.transition(ControllerState.FINISHED)
    assert session.allows_cleanup() is True
