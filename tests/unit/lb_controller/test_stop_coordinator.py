"""Unit tests for the StopCoordinator state machine."""

import time
from unittest.mock import MagicMock

import pytest

from lb_controller.stop_coordinator import StopCoordinator, StopState
from lb_runner.events import RunEvent


@pytest.fixture
def coordinator():
    return StopCoordinator(expected_runners={"node1", "node2"}, stop_timeout=1.0)


def make_event(host="node1", status="stopped"):
    return RunEvent(
        run_id="test-run",
        host=host,
        workload="stress",
        repetition=1,
        total_repetitions=1,
        status=status
    )


def test_initial_state(coordinator):
    assert coordinator.state == StopState.IDLE
    assert not coordinator.can_proceed_to_teardown()


def test_initiate_stop_transitions_state(coordinator):
    coordinator.initiate_stop()
    assert coordinator.state == StopState.STOPPING_WORKLOADS
    assert coordinator.start_time is not None


def test_process_event_ignores_when_idle(coordinator):
    # Should do nothing
    coordinator.process_event(make_event(host="node1"))
    assert len(coordinator.confirmed_runners) == 0


def test_process_event_confirms_runner(coordinator):
    coordinator.initiate_stop()
    
    # Confirm node1
    coordinator.process_event(make_event(host="node1", status="stopped"))
    assert "node1" in coordinator.confirmed_runners
    assert coordinator.state == StopState.STOPPING_WORKLOADS

    # Confirm node2 (failed is also a terminal state)
    coordinator.process_event(make_event(host="node2", status="failed"))
    assert "node2" in coordinator.confirmed_runners
    assert coordinator.state == StopState.TEARDOWN_READY
    assert coordinator.can_proceed_to_teardown()


def test_process_event_ignores_unknown_host(coordinator):
    coordinator.initiate_stop()
    coordinator.process_event(make_event(host="unknown"))
    assert len(coordinator.confirmed_runners) == 0


def test_process_event_ignores_running_status(coordinator):
    coordinator.initiate_stop()
    coordinator.process_event(make_event(host="node1", status="running"))
    assert "node1" not in coordinator.confirmed_runners


def test_timeout_transitions_to_failed(coordinator):
    coordinator.initiate_stop()
    # Mock time to force timeout
    coordinator.start_time = time.time() - 2.0
    
    coordinator.check_timeout()
    assert coordinator.state == StopState.STOP_FAILED
    assert not coordinator.can_proceed_to_teardown()


def test_duplicate_events_handled_gracefully(coordinator):
    coordinator.initiate_stop()
    coordinator.process_event(make_event(host="node1"))
    coordinator.process_event(make_event(host="node1"))
    assert len(coordinator.confirmed_runners) == 1
