"""Controller state machine primitives."""

from __future__ import annotations

import threading
from enum import Enum
from typing import Callable, Optional


class ControllerState(str, Enum):
    """Phase-aware controller lifecycle states."""

    INIT = "init"
    RUNNING_GLOBAL_SETUP = "running_global_setup"
    RUNNING_WORKLOADS = "running_workloads"
    RUNNING_GLOBAL_TEARDOWN = "running_global_teardown"
    STOP_ARMED = "stop_armed"
    STOPPING_INTERRUPT_SETUP = "stopping_interrupt_setup"
    STOPPING_WAIT_RUNNERS = "stopping_wait_runners"
    STOPPING_TEARDOWN = "stopping_teardown"
    STOPPING_INTERRUPT_TEARDOWN = "stopping_interrupt_teardown"
    FINISHED = "finished"
    ABORTED = "aborted"
    STOP_FAILED = "stop_failed"
    FAILED = "failed"


_TERMINAL_STATES = {
    ControllerState.FINISHED,
    ControllerState.ABORTED,
    ControllerState.STOP_FAILED,
    ControllerState.FAILED,
}


_ALLOWED_TRANSITIONS = {
    ControllerState.INIT: {
        ControllerState.RUNNING_GLOBAL_SETUP,
        ControllerState.RUNNING_WORKLOADS,
        ControllerState.RUNNING_GLOBAL_TEARDOWN,
        ControllerState.STOP_ARMED,
        ControllerState.FINISHED,
        ControllerState.ABORTED,
        ControllerState.FAILED,
    },
    ControllerState.RUNNING_GLOBAL_SETUP: {
        ControllerState.RUNNING_WORKLOADS,
        ControllerState.RUNNING_GLOBAL_TEARDOWN,
        ControllerState.STOP_ARMED,
        ControllerState.STOPPING_INTERRUPT_SETUP,
        ControllerState.FAILED,
    },
    ControllerState.RUNNING_WORKLOADS: {
        ControllerState.RUNNING_GLOBAL_TEARDOWN,
        ControllerState.STOP_ARMED,
        ControllerState.STOPPING_WAIT_RUNNERS,
        ControllerState.FAILED,
    },
    ControllerState.RUNNING_GLOBAL_TEARDOWN: {
        ControllerState.FINISHED,
        ControllerState.STOP_ARMED,
        ControllerState.STOPPING_INTERRUPT_TEARDOWN,
        ControllerState.FAILED,
    },
    ControllerState.STOP_ARMED: {
        ControllerState.STOPPING_INTERRUPT_SETUP,
        ControllerState.STOPPING_WAIT_RUNNERS,
        ControllerState.STOPPING_INTERRUPT_TEARDOWN,
        ControllerState.STOPPING_TEARDOWN,
        ControllerState.ABORTED,
        ControllerState.FAILED,
    },
    ControllerState.STOPPING_INTERRUPT_SETUP: {
        ControllerState.STOPPING_TEARDOWN,
        ControllerState.ABORTED,
        ControllerState.STOP_FAILED,
        ControllerState.FAILED,
    },
    ControllerState.STOPPING_WAIT_RUNNERS: {
        ControllerState.STOPPING_TEARDOWN,
        ControllerState.STOP_FAILED,
        ControllerState.FAILED,
    },
    ControllerState.STOPPING_TEARDOWN: {
        ControllerState.ABORTED,
        ControllerState.STOP_FAILED,
        ControllerState.FAILED,
    },
    ControllerState.STOPPING_INTERRUPT_TEARDOWN: {
        ControllerState.STOP_FAILED,
        ControllerState.ABORTED,
        ControllerState.FAILED,
    },
    ControllerState.FINISHED: set(),
    ControllerState.ABORTED: set(),
    ControllerState.STOP_FAILED: set(),
    ControllerState.FAILED: set(),
}


class ControllerStateMachine:
    """Thread-safe controller state tracker."""

    def __init__(self) -> None:
        self._state = ControllerState.INIT
        self._lock = threading.RLock()
        self._reason: Optional[str] = None
        self._callbacks: list[Callable[[ControllerState, Optional[str]], None]] = []

    @property
    def state(self) -> ControllerState:
        with self._lock:
            return self._state

    @property
    def reason(self) -> Optional[str]:
        with self._lock:
            return self._reason

    def is_terminal(self) -> bool:
        with self._lock:
            return self._state in _TERMINAL_STATES

    def allows_cleanup(self) -> bool:
        with self._lock:
            return self._state in {
                ControllerState.FINISHED,
                ControllerState.ABORTED,
            }

    def register_callback(
        self, callback: Callable[[ControllerState, Optional[str]], None]
    ) -> None:
        """Register a callback invoked on every transition."""
        self._callbacks.append(callback)

    def transition(
        self, new_state: ControllerState, reason: Optional[str] = None
    ) -> ControllerState:
        """Attempt a state transition; raise ValueError if invalid."""
        with self._lock:
            allowed = _ALLOWED_TRANSITIONS.get(self._state, set())
            if new_state not in allowed and new_state not in {
                ControllerState.FAILED,
                ControllerState.ABORTED,
                ControllerState.STOP_FAILED,
            }:
                raise ValueError(f"Invalid transition {self._state} -> {new_state}")
            self._state = new_state
            self._reason = reason
            for cb in list(self._callbacks):
                try:
                    cb(self._state, self._reason)
                except Exception:
                    continue
            return self._state

    def snapshot(self) -> tuple[ControllerState, Optional[str]]:
        with self._lock:
            return self._state, self._reason
