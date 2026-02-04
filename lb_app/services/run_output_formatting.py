"""Formatting helpers for run output."""

from __future__ import annotations

import re
from typing import Any

from .run_output_parsing import _extract_lb_event_data


def _slug_phase_label(phase: str) -> str:
    """Normalize phase labels for consistent rendering."""
    cleaned = phase.replace(":", "-").strip()
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", cleaned)
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    return cleaned.strip("-").lower() or "run"


def format_bullet_line(
    phase: str,
    message: str,
    host_label: str | None = None,
) -> str:
    """Format a log line with a phase tag and optional host label."""
    phase_clean = _slug_phase_label(phase)
    host_prefix = f"({host_label}) " if host_label else ""
    return f"• [{phase_clean}] {host_prefix}{message}"


def format_progress_event(
    data: dict[str, Any],
) -> tuple[str, str, str | None]:
    """Render parsed LB_EVENT payloads into concise progress messages."""
    evt_type = data.get("type", "status")
    if evt_type == "log":
        return _format_log_event(data)
    return _format_status_event(data)


def _format_log_event(data: dict[str, Any]) -> tuple[str, str, str | None]:
    host_label = _event_host_label(data)
    workload = _event_workload(data)
    level = data.get("level", "INFO")
    msg = data.get("message", "")
    phase = _run_phase(workload)
    return phase, f"[{level}] {msg}", host_label


def _format_status_event(data: dict[str, Any]) -> tuple[str, str, str | None]:
    host_label = _event_host_label(data)
    workload = _event_workload(data)
    rep, total = _event_repetition(data)
    status = (data.get("status") or "").lower()
    message = _format_status_message(rep, total, status, data)
    phase = _run_phase(workload)
    if _is_terminal_status(status):
        return phase, message, host_label
    return phase, f"{rep}/{total} {status}", host_label


def _event_host_label(data: dict[str, Any]) -> str | None:
    host = data.get("host")
    return str(host) if host else None


def _event_workload(data: dict[str, Any]) -> str:
    return str(data.get("workload") or "?")


def _event_repetition(data: dict[str, Any]) -> tuple[Any, Any]:
    rep = data.get("repetition", "?")
    total = data.get("total_repetitions") or data.get("total") or "?"
    return rep, total


def _format_status_message(
    rep: Any, total: Any, status: str, data: dict[str, Any]
) -> str:
    message = f"{rep}/{total} {status}"
    if data.get("message"):
        message = f"{message} ({data['message']})"
    if data.get("error_type"):
        message = f"{message} [{data['error_type']}]"
    return message


def _run_phase(workload: str) -> str:
    return f"run {workload}"


def _is_terminal_status(status: str) -> bool:
    return status in {"running", "done", "failed"}


def format_progress_line(
    line: str, *, suppress_progress: bool = False
) -> tuple[str, str, str | None] | None:
    """Parse and render LB_EVENT lines into progress messages."""
    if suppress_progress:
        return None
    data = _extract_lb_event_data(line, token="LB_EVENT")
    if not data:
        return None
    return format_progress_event(data)
