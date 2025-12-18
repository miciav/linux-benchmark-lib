"""Controller state machine primitives."""

from __future__ import annotations

import threading
from enum import Enum
from typing import Optional


class ControllerState(str, Enum):
    """High-level lifecycle states for the controller."""

    INIT = "init"
    PROVISIONING = "provisioning"
    SETUP = "setup"
    RUNNING = "running"
    COLLECTING = "collecting"
    TEARDOWN = "teardown"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


_ALLOWED_TRANSITIONS = {
    ControllerState.INIT: {
        ControllerState.PROVISIONING,
        ControllerState.SETUP,
        ControllerState.RUNNING,
        ControllerState.ABORTED,
    },
    ControllerState.PROVISIONING: {
        ControllerState.SETUP,
        ControllerState.RUNNING,
        ControllerState.ABORTED,
        ControllerState.FAILED,
    },
    ControllerState.SETUP: {
        ControllerState.RUNNING,
        ControllerState.TEARDOWN,
        ControllerState.ABORTED,
        ControllerState.FAILED,
    },
    ControllerState.RUNNING: {
        ControllerState.COLLECTING,
        ControllerState.TEARDOWN,
        ControllerState.ABORTED,
        ControllerState.FAILED,
        ControllerState.COMPLETED,
    },
    ControllerState.COLLECTING: {
        ControllerState.TEARDOWN,
        ControllerState.ABORTED,
        ControllerState.FAILED,
        ControllerState.COMPLETED,
    },
    ControllerState.TEARDOWN: {
        ControllerState.COMPLETED,
        ControllerState.FAILED,
        ControllerState.ABORTED,
    },
    ControllerState.COMPLETED: set(),
    ControllerState.FAILED: set(),
    ControllerState.ABORTED: set(),
}


class ControllerStateMachine:
    """Thread-safe controller state tracker."""

    def __init__(self) -> None:
        self._state = ControllerState.INIT
        self._lock = threading.RLock()
        self._reason: Optional[str] = None

    @property
    def state(self) -> ControllerState:
        with self._lock:
            return self._state

    @property
    def reason(self) -> Optional[str]:
        with self._lock:
            return self._reason

    def transition(self, new_state: ControllerState, reason: Optional[str] = None) -> ControllerState:
        """Attempt a state transition; raise ValueError if invalid."""
        with self._lock:
            allowed = _ALLOWED_TRANSITIONS.get(self._state, set())
            if new_state not in allowed and new_state not in {
                ControllerState.FAILED,
                ControllerState.ABORTED,
            }:
                raise ValueError(f"Invalid transition {self._state} -> {new_state}")
            self._state = new_state
            self._reason = reason
            return self._state
