"""Logging handler that emits logs as structured LB_EVENT JSON lines."""

from __future__ import annotations

import logging
import json
import sys
from typing import Any

from lb_common.log_schema import StructuredLogEvent


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
        component: str = "runner",
    ) -> None:
        super().__init__()
        self.run_id = run_id
        self.host = host
        self.workload = workload
        self.repetition = repetition
        self.total_repetitions = total_repetitions
        self.component = component

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            event = StructuredLogEvent.from_log_record(
                record,
                component=self.component,
                host=self.host,
                run_id=self.run_id,
                event_type="log",
                workload=self.workload,
                repetition=self.repetition,
            )
            payload = event.model_dump(mode="json", exclude_none=True)
            payload.update(
                {
                    "workload": self.workload,
                    "repetition": self.repetition,
                    "total_repetitions": self.total_repetitions,
                    "status": "running",
                    "type": "log",
                    "message": message,
                }
            )
            # Use direct print to stdout to ensure Ansible captures it
            # We must flush to ensure real-time streaming
            print(f"LB_EVENT {json.dumps(payload)}", file=sys.stdout, flush=True)
        except Exception:
            self.handleError(record)
