"""RunLifecycle state machine tests."""

import pytest

from lb_controller.lifecycle import RunLifecycle, RunPhase, StopStage

pytestmark = pytest.mark.unit


def test_lifecycle_phase_and_finish():
    lifecycle = RunLifecycle()
    lifecycle.start_phase(RunPhase.GLOBAL_SETUP)
    assert lifecycle.phase == RunPhase.GLOBAL_SETUP
    lifecycle.start_phase(RunPhase.WORKLOADS)
    assert lifecycle.phase == RunPhase.WORKLOADS
    lifecycle.finish()
    assert lifecycle.phase == RunPhase.FINISHED


def test_lifecycle_stop_transitions():
    lifecycle = RunLifecycle()
    lifecycle.arm_stop()
    assert lifecycle.stop_stage == StopStage.ARMED
    lifecycle.mark_waiting_runners()
    assert lifecycle.stop_stage == StopStage.WAITING_FOR_RUNNERS
    lifecycle.mark_failed()
    assert lifecycle.stop_stage == StopStage.FAILED
