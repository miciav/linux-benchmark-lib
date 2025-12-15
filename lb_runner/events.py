"""Structured events for run logging and progress tracking."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
import json


@dataclass
class RunEvent:
    """A structured event emitted during a run."""
    run_id: str
    host: str
    workload: str
    repetition: int
    total_repetitions: int
    status: str  # running | done | failed | skipped
    message: str = ""
    timestamp: float = 0.0
    type: str = "status"
    level: str = "INFO"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


class StdoutEmitter:
    """Emit progress markers to stdout for parsing in Ansible streams."""

    def emit(self, event: RunEvent) -> None:
        print(f"LB_EVENT {event.to_json()}", flush=True)
