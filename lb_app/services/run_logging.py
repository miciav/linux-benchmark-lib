"""Logging helpers for controller run orchestration."""

from __future__ import annotations

from typing import IO, Callable

from lb_controller.api import ControllerState
from lb_app.services.run_types import _RemoteSession
from lb_app.ui_interfaces import DashboardHandle, UIAdapter


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
        if ui_adapter:
            ui_adapter.show_warning(log_msg)
        elif session.dashboard:
            session.dashboard.add_log(display_msg)
            session.dashboard.refresh()
        else:
            print(log_msg)
        try:
            session.log_file.write(log_msg + "\n")
            session.log_file.flush()
            if session.ui_stream_log_file:
                session.ui_stream_log_file.write(log_msg + "\n")
                session.ui_stream_log_file.flush()
        except Exception:
            pass

    return _announce_stop


def log_completion(
    elapsed: float,
    session: _RemoteSession,
    ui_adapter: UIAdapter | None,
) -> None:
    """Log run completion to sinks."""
    msg = f"Run {session.effective_run_id} completed in {elapsed:.1f}s"
    try:
        session.log_file.write(msg + "\n")
        session.log_file.flush()
        if session.ui_stream_log_file:
            session.ui_stream_log_file.write(msg + "\n")
            session.ui_stream_log_file.flush()
    except Exception:
        pass
    if ui_adapter:
        ui_adapter.show_info(msg)
    elif session.dashboard:
        session.dashboard.add_log(msg)
    else:
        print(msg)


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
    try:
        session.log_file.write(line + "\n")
        session.log_file.flush()
        if session.ui_stream_log_file:
            session.ui_stream_log_file.write(line + "\n")
            session.ui_stream_log_file.flush()
    except Exception:
        pass
    if session.journal:
        try:
            session.journal.metadata["controller_state"] = new_state.value
            session.journal.save(session.journal_path)
        except Exception:
            pass
    if session.dashboard:
        try:
            if hasattr(session.dashboard, "set_controller_state"):
                session.dashboard.set_controller_state(new_state.value)
            session.dashboard.refresh()
        except Exception:
            pass
    elif ui_adapter:
        try:
            ui_adapter.show_info(line)
        except Exception:
            pass


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
    if ui_adapter:
        try:
            ui_adapter.show_warning(message)
        except Exception:
            pass
    if dashboard:
        try:
            if hasattr(dashboard, "set_warning"):
                dashboard.set_warning(message, ttl=ttl)
        except Exception:
            pass
        try:
            dashboard.refresh()
        except Exception:
            pass
    else:
        print(message)
    try:
        log_file.write(message + "\n")
        log_file.flush()
        if ui_stream_log_file:
            ui_stream_log_file.write(message + "\n")
            ui_stream_log_file.flush()
    except Exception:
        pass
