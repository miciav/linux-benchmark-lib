"""Unit tests for SIGINT interrupt state handling."""

import pytest

from lb_controller.interrupts import (
    DoubleCtrlCStateMachine,
    RunInterruptState,
    SigintDecision,
)

pytestmark = pytest.mark.unit_controller


def test_double_ctrl_c_arms_then_requests_stop() -> None:
    sm = DoubleCtrlCStateMachine()

    decision = sm.on_sigint(run_active=True)
    assert decision == SigintDecision.WARN_ARM
    assert sm.state == RunInterruptState.STOP_ARMED

    decision = sm.on_sigint(run_active=True)
    assert decision == SigintDecision.REQUEST_STOP
    assert sm.state == RunInterruptState.STOPPING


def test_double_ctrl_c_delegates_when_inactive() -> None:
    sm = DoubleCtrlCStateMachine()
    decision = sm.on_sigint(run_active=False)
    assert decision == SigintDecision.DELEGATE
    assert sm.state == RunInterruptState.RUNNING


def test_double_ctrl_c_delegates_after_finished() -> None:
    sm = DoubleCtrlCStateMachine()
    sm.mark_finished()
    decision = sm.on_sigint(run_active=True)
    assert decision == SigintDecision.DELEGATE
    assert sm.state == RunInterruptState.FINISHED


def test_ctrl_c_is_ignored_while_stopping() -> None:
    sm = DoubleCtrlCStateMachine()
    sm.on_sigint(run_active=True)
    sm.on_sigint(run_active=True)
    decision = sm.on_sigint(run_active=True)
    assert decision == SigintDecision.IGNORE
    assert sm.state == RunInterruptState.STOPPING
