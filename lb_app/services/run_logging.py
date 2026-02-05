"""Logging helpers for controller run orchestration."""

from __future__ import annotations

import logging
from typing import IO, Callable

from lb_controller.api import ControllerState
from lb_app.services.run_types import _RemoteSession
from lb_app.ui_interfaces import DashboardHandle, UIAdapter

logger = logging.getLogger(__name__)


def _write_log_files(
    log_file: IO[str], ui_stream_log_file: IO[str] | None, message: str
) -> None:
    try:
        log_file.write(message + "\n")
        log_file.flush()
        if ui_stream_log_file:
            ui_stream_log_file.write(message + "\n")
            ui_stream_log_file.flush()
    except Exception:
        pass


def _emit_ui_message(
    message: str,
    *,
    level: str,
    ui_adapter: UIAdapter | None,
    dashboard: DashboardHandle | None,
    dashboard_message: str | None = None,
    dashboard_warning: bool = False,
    ttl: float = 10.0,
) -> None:
    if _emit_via_ui(ui_adapter, level, message):
        return
    if _emit_via_dashboard(
        dashboard,
        message,
        dashboard_message=dashboard_message,
        dashboard_warning=dashboard_warning,
        ttl=ttl,
    ):
        return
    print(message)


def _emit_via_ui(ui_adapter: UIAdapter | None, level: str, message: str) -> bool:
    if not ui_adapter:
        return False
    try:
        if level == "warning":
            ui_adapter.show_warning(message)
        else:
            ui_adapter.show_info(message)
    except Exception:
        return True
    return True


def _emit_via_dashboard(
    dashboard: DashboardHandle | None,
    message: str,
    *,
    dashboard_message: str | None,
    dashboard_warning: bool,
    ttl: float,
) -> bool:
    if not dashboard:
        return False
    msg = dashboard_message or message
    try:
        if dashboard_warning and hasattr(dashboard, "set_warning"):
            dashboard.set_warning(message, ttl=ttl)
        else:
            dashboard.add_log(msg)
    except Exception:
        pass
    try:
        dashboard.refresh()
    except Exception:
        pass
    return True


def controller_stop_hint(message: str) -> tuple[str, str]:
    """Return colored dashboard text and plain log text for stop notices."""
    tag_plain = "[Controller]"
    tag_styled = "[bold bright_magenta][Controller][/bold bright_magenta]"
    base = message.lstrip()
    return f"{tag_styled} {base}", f"{tag_plain} {base}"


def announce_stop_factory(
    session: _RemoteSession,
    ui_adapter: UIAdapter | None,
    hint_factory: Callable[[str], tuple[str, str]] = controller_stop_hint,
) -> Callable[[str], None]:
    """Create a stop announcer that logs to UI/dashboard."""
    stop_announced = {"value": False}

    def _announce_stop(
        msg: str = "Stop confirmed; initiating teardown and aborting the run.",
    ) -> None:
        if stop_announced["value"]:
            return
        stop_announced["value"] = True
        try:
            session.controller_state.transition(ControllerState.STOP_ARMED, reason=msg)
        except Exception:
            pass
        display_msg, log_msg = hint_factory(msg)
        logger.info("%s", log_msg)
        _emit_ui_message(
            log_msg,
            level="warning",
            ui_adapter=ui_adapter,
            dashboard=session.dashboard,
            dashboard_message=display_msg,
        )
        _write_log_files(session.log_file, session.ui_stream_log_file, log_msg)

    return _announce_stop


def log_completion(
    elapsed: float,
    session: _RemoteSession,
    ui_adapter: UIAdapter | None,
) -> None:
    """Log run completion to sinks."""
    msg = f"Run {session.effective_run_id} completed in {elapsed:.1f}s"
    logger.info("%s", msg)
    _write_log_files(session.log_file, session.ui_stream_log_file, msg)
    _emit_ui_message(
        msg,
        level="info",
        ui_adapter=ui_adapter,
        dashboard=session.dashboard,
    )


def on_controller_state_change(
    new_state: ControllerState,
    reason: str | None,
    session: _RemoteSession,
    ui_adapter: UIAdapter | None,
) -> None:
    """Handle controller state transitions consistently."""
    line = f"Controller state: {new_state.value}"
    if reason:
        line = f"{line} ({reason})"
    logger.info("%s", line)
    _write_log_files(session.log_file, session.ui_stream_log_file, line)
    _update_journal_state(session, new_state)
    if not _update_dashboard_state(session, new_state):
        _emit_via_ui(ui_adapter, "info", line)


def _update_journal_state(session: _RemoteSession, new_state: ControllerState) -> None:
    if not session.journal:
        return
    try:
        session.journal.metadata["controller_state"] = new_state.value
        session.journal.save(session.journal_path)
    except Exception:
        pass


def _update_dashboard_state(
    session: _RemoteSession, new_state: ControllerState
) -> bool:
    if not session.dashboard:
        return False
    try:
        if hasattr(session.dashboard, "set_controller_state"):
            session.dashboard.set_controller_state(new_state.value)
        session.dashboard.refresh()
    except Exception:
        pass
    return True


def emit_warning(
    message: str,
    *,
    dashboard: DashboardHandle | None,
    ui_adapter: UIAdapter | None,
    log_file: IO[str],
    ui_stream_log_file: IO[str] | None,
    ttl: float = 10.0,
) -> None:
    """Send a warning to UI, dashboard, and logs in a consistent way."""
    logger.warning("%s", message)
    _emit_ui_message(
        message,
        level="warning",
        ui_adapter=ui_adapter,
        dashboard=dashboard,
        dashboard_warning=True,
        ttl=ttl,
    )
    _write_log_files(log_file, ui_stream_log_file, message)
