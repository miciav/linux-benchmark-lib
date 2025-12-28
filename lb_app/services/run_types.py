"""Shared dataclasses for run orchestration."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
import queue
import threading
from typing import IO, TYPE_CHECKING, Any, Callable, Dict, Optional

from lb_controller.api import (
    ControllerStateMachine,
    DoubleCtrlCStateMachine,
    LogSink,
    RunJournal,
)
from lb_app.ui_interfaces import DashboardHandle
from lb_controller.api import BenchmarkConfig, RunEvent, StopToken
from lb_plugins.api import PluginRegistry

if TYPE_CHECKING:
    from lb_controller.api import BenchmarkController, RunExecutionSummary


@dataclass
class RunContext:
    """Inputs required to execute a run."""

    config: BenchmarkConfig
    target_tests: list[str]
    registry: PluginRegistry
    config_path: Optional[Path] = None
    debug: bool = False
    resume_from: str | None = None
    resume_latest: bool = False
    stop_file: Path | None = None
    execution_mode: str = "remote"
    node_count: int | None = None


@dataclass
class RunResult:
    """Outcome of a run."""

    context: RunContext
    summary: Optional[RunExecutionSummary]
    journal_path: Path | None = None
    log_path: Path | None = None
    ui_log_path: Path | None = None


@dataclass
class _RemoteSession:
    """Session-scoped state for a remote run."""

    journal: RunJournal
    journal_path: Path
    dashboard: DashboardHandle
    ui_stream_log_file: IO[str] | None
    ui_stream_log_path: Path | None
    log_path: Path
    log_file: IO[str]
    sink: LogSink
    stop_token: StopToken
    effective_run_id: str
    controller_state: ControllerStateMachine
    resume_requested: bool


@dataclass
class _EventPipeline:
    """Event/output wiring for a controller run."""

    output_cb: Callable[[str, str], None]
    announce_stop: Callable[[str], None]
    ingest_event: Callable[[RunEvent, str], None]
    event_from_payload: Callable[[Dict[str, Any]], RunEvent | None]
    sink: LogSink
    controller_ref: dict[str, "BenchmarkController" | None]


@dataclass
class _SignalContext:
    """State for SIGINT handling during controller runs."""

    events: queue.SimpleQueue[tuple[str, str | None]]
    state_machine: DoubleCtrlCStateMachine
    warning_timer: threading.Timer | None = None


@dataclass
class _EventDedupe:
    """Track recent events to avoid duplicate fan-out."""

    recent_events: deque[tuple[str, str, int, str, str, str]] = field(
        default_factory=deque
    )
    recent_set: set[tuple[str, str, int, str, str, str]] = field(default_factory=set)
    limit: int = 200

    def record(self, event: RunEvent) -> bool:
        """Return True if the event is new within the window."""
        key = (
            event.host,
            event.workload,
            event.repetition,
            event.status,
            event.type,
            event.message,
        )
        if key in self.recent_set:
            return False
        self.recent_events.append(key)
        self.recent_set.add(key)
        if len(self.recent_events) > self.limit:
            old = self.recent_events.popleft()
            self.recent_set.discard(old)
        return True


class _DashboardLogProxy(DashboardHandle):
    """Dashboard wrapper that also writes log lines to a file."""

    def __init__(self, inner: DashboardHandle, log_file: IO[str]):
        self._inner = inner
        self._log_file = log_file

    def live(self):
        return self._inner.live()

    def add_log(self, line: str) -> None:
        if not line or not str(line).strip():
            return
        message = str(line).strip()
        self._inner.add_log(message)
        try:
            self._log_file.write(message + "\n")
            self._log_file.flush()
        except Exception:
            pass

    def refresh(self) -> None:
        self._inner.refresh()

    def mark_event(self, source: str) -> None:
        self._inner.mark_event(source)

    def set_warning(self, message: str, ttl: float = 10.0) -> None:
        setter = getattr(self._inner, "set_warning", None)
        if callable(setter):
            setter(message, ttl)

    def clear_warning(self) -> None:
        clearer = getattr(self._inner, "clear_warning", None)
        if callable(clearer):
            clearer()

    def set_controller_state(self, state: str) -> None:
        setter = getattr(self._inner, "set_controller_state", None)
        if callable(setter):
            setter(state)
