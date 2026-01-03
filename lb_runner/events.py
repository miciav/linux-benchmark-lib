"""Structured events for run logging and progress tracking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping
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
    component: str | None = None
    logger: str | None = None
    event_type: str | None = None
    scenario: str | None = None
    tags: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.event_type is None:
            self.event_type = self.type

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "run_id": self.run_id,
            "host": self.host,
            "workload": self.workload,
            "repetition": self.repetition,
            "total_repetitions": self.total_repetitions,
            "status": self.status,
            "message": self.message,
            "timestamp": self.timestamp,
            "type": self.type,
            "level": self.level,
        }
        if self.component is not None:
            payload["component"] = self.component
        if self.logger is not None:
            payload["logger"] = self.logger
        if self.event_type is not None:
            payload["event_type"] = self.event_type
        if self.scenario is not None:
            payload["scenario"] = self.scenario
        if self.tags is not None:
            payload["tags"] = self.tags
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


class StdoutEmitter:
    """Emit progress markers to stdout for parsing in Ansible streams."""

    def emit(self, event: RunEvent) -> None:
        print(f"LB_EVENT {event.to_json()}", flush=True)
