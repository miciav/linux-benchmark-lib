"""Event pipeline helpers for run orchestration."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Dict

from rich.markup import escape

from lb_app.services.run_events import JsonEventTailer
from lb_app.services.run_output import (
    AnsibleOutputFormatter,
    _extract_lb_event_data,
)
from lb_app.services.run_types import RunContext, _EventDedupe, _RemoteSession
from lb_app.ui_interfaces import DashboardHandle
from lb_runner.api import RunEvent


def pipeline_output_callback(
    dashboard: DashboardHandle | None,
    formatter: AnsibleOutputFormatter | None,
    output_callback: Callable[[str, str], None],
) -> Callable[[str, str], None]:
    """Fan-out formatter output to dashboard when available."""
    if not dashboard or output_callback is None:
        return output_callback

    last_refresh = {"ts": 0.0}

    def _dashboard_callback(text: str, end: str = ""):
        if formatter and output_callback == formatter.process:
            formatter.process(text, end=end, log_sink=dashboard.add_log)
        else:
            output_callback(text, end=end)
            dashboard.add_log(text)
        now = time.monotonic()
        if now - last_refresh["ts"] > 0.25:
            dashboard.refresh()
            last_refresh["ts"] = now

    return _dashboard_callback


def make_ingest_event(
    session: _RemoteSession,
    dashboard: DashboardHandle | None,
    controller_ref: dict[str, Any],
    dedupe: _EventDedupe,
) -> Callable[[RunEvent, str], None]:
    """Return an ingest function that updates journal, controller, and dashboard."""

    def _ingest(event: RunEvent, source: str = "unknown") -> None:
        if not dedupe.record(event):
            return
        session.sink.emit(event)
        controller = controller_ref.get("controller")
        if controller:
            controller.on_event(event)
        mirror_event_to_dashboard(event, dashboard, source)

    return _ingest


def mirror_event_to_dashboard(
    event: RunEvent, dashboard: DashboardHandle | None, source: str
) -> None:
    """Send an event summary to the dashboard when available."""
    if not dashboard:
        return
    dashboard.mark_event(source)
    label = f"run-{event.host}".replace(":", "-").replace(" ", "-")
    label = f"{label}-{event.workload}".replace(":", "-").replace(" ", "-")
    text = f"• [{label}] {event.repetition}/{event.total_repetitions} {event.status}"
    if event.message:
        text = f"{text} ({event.message})"
    dashboard.add_log(escape(text))
    dashboard.refresh()


def event_from_payload_data(
    data: Dict[str, Any], session: _RemoteSession, context: RunContext
) -> RunEvent | None:
    """Convert a JSON payload dict to a RunEvent."""
    required = {"host", "workload", "repetition", "status"}
    if not required.issubset(data.keys()):
        return None
    return RunEvent(
        run_id=session.journal.run_id,
        host=str(data.get("host", "")),
        workload=str(data.get("workload", "")),
        repetition=int(data.get("repetition") or 0),
        total_repetitions=int(
            data.get("total_repetitions")
            or data.get("total")
            or context.config.repetitions
        ),
        status=str(data.get("status", "")),
        message=str(data.get("message") or ""),
        timestamp=time.time(),
        type=str(data.get("type", "status")),
        level=str(data.get("level", "INFO")),
    )


def make_progress_handler(
    session: _RemoteSession,
    context: RunContext,
    ingest_event: Callable[[RunEvent, str], None],
    progress_token: str,
) -> Callable[[str], None]:
    """Return a handler that converts stdout markers into RunEvents."""

    def _handle_progress(line: str) -> None:
        info = parse_progress_line(line, token=progress_token)
        if not info:
            return
        try:
            event = RunEvent(
                run_id=session.journal.run_id,
                host=info["host"],
                workload=info["workload"],
                repetition=info["rep"],
                total_repetitions=info.get("total", context.config.repetitions),
                status=info["status"],
                message=info.get("message") or "",
                timestamp=time.time(),
            )
            ingest_event(event, source="stdout")
        except Exception:
            pass

    return _handle_progress


def make_output_tee(
    session: _RemoteSession,
    downstream: Callable[[str, str], None] | None,
    progress_handler: Callable[[str], None],
) -> Callable[[str, str], None]:
    """Return an output callback that logs, parses progress, and tees downstream."""

    def _tee_output(text: str, end: str = "") -> None:
        fragment = text + (end if end else "\n")
        try:
            session.log_file.write(fragment)
            session.log_file.flush()
        except Exception:
            pass
        for line in fragment.splitlines():
            progress_handler(line)
        if downstream:
            downstream(text, end=end)

    return _tee_output


def maybe_start_event_tailer(
    controller: Any,
    event_from_payload: Callable[[Dict[str, Any]], RunEvent | None],
    ingest_event: Callable[[RunEvent, str], None],
    formatter: AnsibleOutputFormatter | None,
) -> JsonEventTailer | None:
    """Start a callback tailer when the controller provides an event log path."""
    event_log_path = getattr(
        getattr(controller, "executor", None), "event_log_path", None
    )
    if not event_log_path:
        return None

    def _on_event_payload(data: Dict[str, Any]) -> None:
        event = event_from_payload(data)
        if event:
            ingest_event(event, source="callback")

    event_tailer = JsonEventTailer(Path(event_log_path), _on_event_payload)
    if formatter:
        formatter.suppress_progress = True
    event_tailer.start()
    return event_tailer


def parse_progress_line(line: str, token: str) -> dict[str, Any] | None:
    """Parse progress markers emitted by LocalRunner."""
    line = line.strip()
    data = _extract_lb_event_data(line, token=token)
    if not data:
        return None
    required = {"host", "workload", "repetition", "status"}
    if not required.issubset(data.keys()):
        return None
    return {
        "host": data["host"],
        "workload": data["workload"],
        "rep": data.get("repetition", 0),
        "status": data["status"],
        "total": data.get("total_repetitions", 0),
        "message": data.get("message"),
        "type": data.get("type", "status"),
        "level": data.get("level", "INFO"),
    }
