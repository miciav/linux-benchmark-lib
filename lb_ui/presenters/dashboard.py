"""Dashboard viewmodel facade for TUI rendering."""

from __future__ import annotations

from lb_app.api import (
    DashboardLogMetadata,
    DashboardRow,
    DashboardSnapshot,
    DashboardStatusSummary,
    DashboardViewModel,
    build_dashboard_viewmodel,
    event_status_line as _event_status_line,
)
def event_status_line(
    event_source: str, last_event_ts: float | None, *, now: float | None = None
) -> str:
    from lb_ui.tui.core import theme

    status, detail = _event_status_line(event_source, last_event_ts, now=now)
    if status == "waiting":
        return theme.event_status_waiting()
    return theme.event_status_live(event_source, detail)


__all__ = [
    "DashboardLogMetadata",
    "DashboardRow",
    "DashboardSnapshot",
    "DashboardStatusSummary",
    "DashboardViewModel",
    "build_dashboard_viewmodel",
    "event_status_line",
]
