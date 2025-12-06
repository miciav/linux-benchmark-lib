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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


class ProgressEmitter:
    """Dispatch RunEvent instances."""

    def emit(self, event: RunEvent) -> None:
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover - interface hook
        """Optional shutdown hook for emitters."""
        return


class StdoutEmitter(ProgressEmitter):
    """Emit progress markers to stdout for parsing in Ansible streams."""

    def emit(self, event: RunEvent) -> None:
        print(f"LB_EVENT {event.to_json()}", flush=True)


class LogSink:
    """Persist events and mirror them to the run journal and optional stdout/log file."""

    def __init__(self, journal, journal_path: Path, log_file: Path | None = None):
        self.journal = journal
        self.journal_path = journal_path
        self.log_file = log_file
        self._log_handle = None
        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            self._log_handle = log_file.open("a", encoding="utf-8")

    def emit(self, event: RunEvent) -> None:
        """Handle a single event."""
        self._update_journal(event)
        self._write_log(event)

    def emit_many(self, events: Iterable[RunEvent]) -> None:
        for ev in events:
            self.emit(ev)

    def close(self) -> None:
        if self._log_handle:
            try:
                self._log_handle.close()
            except Exception:
                pass
            self._log_handle = None

    def _update_journal(self, event: RunEvent) -> None:
        """Update journal tasks based on event state."""
        from lb_controller.journal import RunStatus

        status_map = {
            "running": RunStatus.RUNNING,
            "done": RunStatus.COMPLETED,
            "failed": RunStatus.FAILED,
            "skipped": RunStatus.SKIPPED,
        }
        mapped = status_map.get(event.status.lower(), RunStatus.RUNNING)
        self.journal.update_task(
            event.host,
            event.workload,
            event.repetition,
            mapped,
            action="run_progress",
            error=event.message if mapped == RunStatus.FAILED else None,
        )
        self.journal.save(self.journal_path)

    def _write_log(self, event: RunEvent) -> None:
        if not self._log_handle:
            return
        ts = datetime.fromtimestamp(event.timestamp or datetime.now().timestamp()).isoformat()
        line = f"[{ts}] {event.host} {event.workload} rep {event.repetition}/{event.total_repetitions} status={event.status}"
        if event.message:
            line += f" msg={event.message}"
        try:
            self._log_handle.write(line + "\n")
            self._log_handle.flush()
        except Exception:
            pass
