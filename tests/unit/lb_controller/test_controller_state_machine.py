import pytest

from lb_controller.controller_state import ControllerState, ControllerStateMachine


pytestmark = pytest.mark.unit_controller


def test_valid_transitions():
    sm = ControllerStateMachine()
    assert sm.state == ControllerState.INIT

    sm.transition(ControllerState.RUNNING_GLOBAL_SETUP)
    assert sm.state == ControllerState.RUNNING_GLOBAL_SETUP

    sm.transition(ControllerState.RUNNING_WORKLOADS)
    assert sm.state == ControllerState.RUNNING_WORKLOADS

    sm.transition(ControllerState.STOP_ARMED)
    sm.transition(ControllerState.STOPPING_WAIT_RUNNERS)
    sm.transition(ControllerState.STOPPING_TEARDOWN)
    sm.transition(ControllerState.ABORTED)
    assert sm.state == ControllerState.ABORTED
    assert sm.is_terminal()
    assert sm.allows_cleanup()


def test_invalid_transition_raises():
    sm = ControllerStateMachine()
    with pytest.raises(ValueError):
        sm.transition(ControllerState.STOPPING_WAIT_RUNNERS)


def test_transition_reason_is_tracked():
    sm = ControllerStateMachine()
    sm.transition(ControllerState.RUNNING_GLOBAL_SETUP, reason="starting infra")
    assert sm.reason == "starting infra"
    sm.transition(ControllerState.FAILED, reason="boom")
    assert sm.reason == "boom"
