"""Threaded runner for BenchmarkController with state notifications."""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable
from typing import Any

from lb_controller.models.state import ControllerState, ControllerStateMachine
from lb_runner.api import StopToken

StateCallback = Callable[[ControllerState, str | None], None]


class ControllerRunner:
    """Run a BenchmarkController in a dedicated thread with state tracking."""

    def __init__(
        self,
        run_callable: Callable[[], Any],
        stop_token: StopToken | None = None,
        on_state_change: StateCallback | None = None,
        state_machine: ControllerStateMachine | None = None,
    ) -> None:
        """Initialize the controller runner.

        Args:
        run_callable: A callable that executes the controller and returns a summary.
        stop_token: Optional stop token to request graceful termination.
        on_state_change: Optional callback invoked on every state transition.

        """
        self._run_callable = run_callable
        self._stop_token = stop_token
        self._machine = state_machine or ControllerStateMachine()
        if on_state_change:
            self._machine.register_callback(on_state_change)
        self._thread: threading.Thread | None = None
        self._result: Any = None
        self._exception: BaseException | None = None
        self._done = threading.Event()

    @property
    def state(self) -> ControllerState:
        return self._machine.state

    @property
    def result(self) -> Any:
        return self._result

    @property
    def exception(self) -> BaseException | None:
        return self._exception

    def start(self) -> None:
        """Start the controller thread."""
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run,
            name="lb-controller-runner",
            daemon=True,
        )
        self._thread.start()

    def wait(self, timeout: float | None = None) -> Any:
        """Block until completion or timeout; re-raise exceptions from the worker."""
        finished = self._done.wait(timeout=timeout)
        if not finished:
            return None
        if self._exception:
            raise self._exception
        return self._result

    def arm_stop(self, reason: str | None = None) -> None:
        """Signal the controller to stop gracefully."""
        # Ignore invalid transition; best-effort arming
        with contextlib.suppress(Exception):
            self._machine.transition(ControllerState.STOP_ARMED, reason=reason)
        if self._stop_token:
            with contextlib.suppress(Exception):
                self._stop_token.request_stop()

    def _run(self) -> None:
        try:
            self._result = self._run_callable()
            self._finalize_success()
        except BaseException as exc:  # pragma: no cover - worker safety
            self._handle_failure(exc)
        finally:
            self._done.set()

    def _finalize_success(self) -> None:
        if self._machine.is_terminal():
            return
        final_state = self._final_state_on_success()
        self._machine.transition(final_state)

    def _handle_failure(self, exc: BaseException) -> None:
        self._exception = exc
        final_state = self._final_state_on_failure()
        try:
            if not self._machine.is_terminal():
                self._machine.transition(final_state, reason=str(exc))
        except Exception:
            with contextlib.suppress(Exception):
                self._machine.transition(ControllerState.FAILED, reason=str(exc))

    def _final_state_on_success(self) -> ControllerState:
        if self._stop_token and self._stop_token.should_stop():
            return ControllerState.ABORTED
        return ControllerState.FINISHED

    def _final_state_on_failure(self) -> ControllerState:
        if self._stop_token and self._stop_token.should_stop():
            return ControllerState.ABORTED
        return ControllerState.FAILED
