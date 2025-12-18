import pytest

from lb_controller.controller_state import ControllerState, ControllerStateMachine


pytestmark = pytest.mark.controller


def test_valid_transitions():
    sm = ControllerStateMachine()
    assert sm.state == ControllerState.INIT

    sm.transition(ControllerState.PROVISIONING)
    assert sm.state == ControllerState.PROVISIONING

    sm.transition(ControllerState.SETUP)
    assert sm.state == ControllerState.SETUP

    sm.transition(ControllerState.RUNNING)
    assert sm.state == ControllerState.RUNNING

    sm.transition(ControllerState.COLLECTING)
    sm.transition(ControllerState.TEARDOWN)
    sm.transition(ControllerState.COMPLETED)
    assert sm.state == ControllerState.COMPLETED


def test_invalid_transition_raises():
    sm = ControllerStateMachine()
    sm.transition(ControllerState.PROVISIONING)
    with pytest.raises(ValueError):
        sm.transition(ControllerState.COMPLETED)


def test_transition_reason_is_tracked():
    sm = ControllerStateMachine()
    sm.transition(ControllerState.PROVISIONING, reason="starting infra")
    assert sm.reason == "starting infra"
    sm.transition(ControllerState.FAILED, reason="boom")
    assert sm.reason == "boom"
