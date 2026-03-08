"""SIGINT (Ctrl+C) handling utilities for long-running runs."""

from __future__ import annotations

import signal
import threading
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from enum import Enum
from types import FrameType, TracebackType

SignalHandler = int | Callable[[int, FrameType | None], object]


def _as_callable_handler(
    handler: SignalHandler | None,
) -> Callable[[int, FrameType | None], object] | None:
    """Return the previous signal handler when it is callable."""
    if callable(handler):
        return handler
    return None


class RunInterruptState(str, Enum):
    """Explicit run/interrupt lifecycle states."""

    RUNNING = "running"
    STOP_ARMED = "stop_armed"
    STOPPING = "stopping"
    FINISHED = "finished"


class SigintDecision(str, Enum):
    """Decision returned by the SIGINT state machine."""

    WARN_ARM = "warn_arm"
    REQUEST_STOP = "request_stop"
    IGNORE = "ignore"
    DELEGATE = "delegate"


@dataclass(slots=True)
class DoubleCtrlCStateMachine:
    """Double-press Ctrl+C confirmation state machine.

    Policy: the second Ctrl+C confirms stop at any time after the first press,
    until the run finishes (no timeout window).
    """

    state: RunInterruptState = RunInterruptState.RUNNING

    def on_sigint(self, *, run_active: bool) -> SigintDecision:
        """Process a SIGINT and return what the caller should do next."""
        if not run_active or self.state == RunInterruptState.FINISHED:
            return SigintDecision.DELEGATE

        if self.state == RunInterruptState.RUNNING:
            self.state = RunInterruptState.STOP_ARMED
            return SigintDecision.WARN_ARM

        if self.state == RunInterruptState.STOP_ARMED:
            self.state = RunInterruptState.STOPPING
            return SigintDecision.REQUEST_STOP

        # In STOPPING we swallow further Ctrl+C while the run is active to avoid
        # tearing down the process; the caller can still expose an explicit exit.
        return SigintDecision.IGNORE

    def mark_finished(self) -> None:
        """Transition to FINISHED and disable further confirmation handling."""
        self.state = RunInterruptState.FINISHED

    def reset_arm(self) -> None:
        """Return to RUNNING from STOP_ARMED after a timeout window."""
        if self.state == RunInterruptState.STOP_ARMED:
            self.state = RunInterruptState.RUNNING


class SigintDoublePressHandler(AbstractContextManager["SigintDoublePressHandler"]):
    """Installs a SIGINT handler that implements double-press confirmation."""

    def __init__(
        self,
        *,
        state_machine: DoubleCtrlCStateMachine,
        run_active: Callable[[], bool],
        on_first_sigint: Callable[[], None],
        on_confirmed_sigint: Callable[[], None],
    ) -> None:
        self._sm = state_machine
        self._run_active = run_active
        self._on_first = on_first_sigint
        self._on_confirmed = on_confirmed_sigint
        self._prev_handler: SignalHandler | None = None

    def __enter__(self) -> "SigintDoublePressHandler":
        if threading.current_thread() is not threading.main_thread():
            return self
        self._prev_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, self._handle_sigint)
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        if self._prev_handler is not None:
            signal.signal(signal.SIGINT, self._prev_handler)
        self._sm.mark_finished()

    def _delegate(self, signum: int, frame: FrameType | None) -> None:
        prev = self._prev_handler
        if prev is None or prev == signal.SIG_IGN:
            return
        if prev == signal.SIG_DFL:
            signal.default_int_handler(signum, frame)
        callable_handler = _as_callable_handler(prev)
        if callable_handler is None:
            signal.default_int_handler(signum, frame)
        callable_handler(signum, frame)

    def _handle_sigint(self, signum: int, frame: FrameType | None) -> None:
        decision = self._sm.on_sigint(run_active=self._run_active())
        if decision == SigintDecision.WARN_ARM:
            self._on_first()
            return
        if decision == SigintDecision.REQUEST_STOP:
            self._on_confirmed()
            return
        if decision == SigintDecision.IGNORE:
            return
        self._delegate(signum, frame)
