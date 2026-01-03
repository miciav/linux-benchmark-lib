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
        total_repetitions: int
    ) -> None:
        super().__init__()
        self.run_id = run_id
        self.host = host
        self.workload = workload
        self.repetition = repetition
        self.total_repetitions = total_repetitions

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            payload = {
                "run_id": self.run_id,
                "host": self.host,
                "workload": self.workload,
                "repetition": self.repetition,
                "total_repetitions": self.total_repetitions,
                "status": "running",
                "type": "log",
                "level": record.levelname,
                "message": msg,
                "timestamp": record.created,
                "logger": record.name
            }
            # Use direct print to stdout to ensure Ansible captures it
            # We must flush to ensure real-time streaming
            print(f"LB_EVENT {json.dumps(payload)}", file=sys.stdout, flush=True)
        except Exception:
            self.handleError(record)
