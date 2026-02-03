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
    host = str(data.get("host") or "")
    workload = str(data.get("workload") or "?")
    rep = data.get("repetition", "?")
    total = data.get("total_repetitions") or data.get("total") or "?"
    status = (data.get("status") or "").lower()
    evt_type = data.get("type", "status")

    if evt_type == "log":
        level = data.get("level", "INFO")
        msg = data.get("message", "")
        phase = f"run {workload}"
        return phase, f"[{level}] {msg}", host or None

    message = f"{rep}/{total} {status}"
    if data.get("message"):
        message = f"{message} ({data['message']})"
    if data.get("error_type"):
        message = f"{message} [{data['error_type']}]"
    phase = f"run {workload}"
    if status in {"running", "done", "failed"}:
        return phase, message, host or None
    return phase, f"{rep}/{total} {status}", host or None


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
