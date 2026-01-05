"""Logging handler that emits logs as structured LB_EVENT JSON lines."""

from __future__ import annotations

import logging
import json
import sys


class LBEventLogHandler(logging.Handler):
    """
    Logging handler that emits logs as structured LB_EVENT JSON lines
    to stdout, allowing the controller to capture and stream them.
    """
    def __init__(
        self,
        run_id: str,
        host: str,
        workload: str,
        repetition: int,
        total_repetitions: int,
        stdout_emitter: Any | None = None,
    ) -> None:
        super().__init__()
        self.run_id = run_id
        self.host = host
        self.workload = workload
        self.repetition = repetition
        self.total_repetitions = total_repetitions
        self._stdout_emitter = stdout_emitter

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            from lb_runner.models.events import RunEvent
            event = RunEvent(
                run_id=self.run_id,
                host=self.host,
                workload=self.workload,
                repetition=self.repetition,
                total_repetitions=self.total_repetitions,
                status="running",
                type="log",
                level=record.levelname,
                message=msg,
                timestamp=record.created,
            )
            
            if self._stdout_emitter:
                self._stdout_emitter.emit(event)
            else:
                # Fallback to direct print
                print(f"LB_EVENT {event.to_json()}", file=sys.stdout, flush=True)
        except Exception:
            self.handleError(record)
