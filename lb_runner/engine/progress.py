"""Helpers for emitting structured run progress events."""

from __future__ import annotations

import logging
import time
from typing import Callable

from lb_runner.models.events import RunEvent, StdoutEmitter


logger = logging.getLogger(__name__)


class RunProgressEmitter:
    """Emit progress events to callbacks and stdout."""

    def __init__(
        self,
        host: str,
        callback: Callable[[RunEvent], None] | None = None,
        stdout_emitter: StdoutEmitter | None = None,
    ) -> None:
        self._host = host
        self._callback = callback
        self._stdout_emitter = stdout_emitter or StdoutEmitter()
        self._run_id = ""

    def set_run_id(self, run_id: str) -> None:
        """Set the active run identifier for emitted events."""
        self._run_id = run_id

    def emit(
        self,
        workload: str,
        repetition: int,
        total_repetitions: int,
        status: str,
    ) -> None:
        """Notify progress callback and stdout marker for remote parsing."""
        event = RunEvent(
            run_id=self._run_id,
            host=self._host,
            workload=workload,
            repetition=repetition,
            total_repetitions=total_repetitions,
            status=status,
            timestamp=time.time(),
        )
        if self._callback:
            try:
                self._callback(event)
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("Progress callback failed: %s", exc)
        try:
            self._stdout_emitter.emit(event)
        except Exception:
            # Never break workload on progress path
            pass
