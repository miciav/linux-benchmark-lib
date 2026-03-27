"""Rich dashboard rendering for the run journal."""

from __future__ import annotations

import os
import select
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import IO, List

try:
    import termios
    import tty
except ImportError:  # pragma: no cover - non-POSIX fallback
    termios = None  # type: ignore[assignment]
    tty = None  # type: ignore[assignment]

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from lb_ui.presenters.dashboard import (
    DashboardSnapshot,
    DashboardViewModel,
    event_status_parts,
)
from lb_ui.tui.core.protocols import Dashboard, DashboardFactory
from lb_ui.tui.core import theme
from lb_ui.tui.system.components import dashboard_helpers
from lb_ui.tui.system.components.dashboard_rollup import PollingRollupHelper


class RichDashboard(Dashboard):
    """Render run plan and journal tables with Live refreshes."""

    def __init__(
        self,
        console: Console,
        viewmodel: DashboardViewModel,
        ui_log_file: IO[str] | None = None,
    ) -> None:
        self.console = console
        self.viewmodel = viewmodel
        self.log_buffer: List[str] = []
        self.raw_log_buffer: List[str] = []
        self.max_log_lines = 20
        self._rollup_helper = PollingRollupHelper(self.log_buffer, summary_only=True)
        self.layout = Layout()
        self.layout.split_column(
            Layout(name="journal"),
            Layout(name="status", size=5, minimum_size=5),
            Layout(name="logs"),
        )
        self._live: Live | None = None
        self.event_source: str = "waiting"
        self.last_event_ts: float | None = None
        self.ui_log_file = ui_log_file
        self.controller_state: str = "starting\u2026"
        self._warning_message: str | None = None
        self._warning_expires_at: float | None = None
        self._log_mode = "summary"
        self._key_listener_thread: threading.Thread | None = None
        self._key_listener_stop = threading.Event()

    @contextmanager
    def live(self) -> Iterator[None]:
        """Context manager that drives Live updates."""
        if self._live is not None:
            yield None
            return
        with Live(
            self.render(),
            console=self.console,
            refresh_per_second=4,
            screen=True,
        ) as live:
            self._live = live
            self._start_key_listener()
            try:
                yield None
            finally:
                self._stop_key_listener()
                self._live = None

    def refresh(self) -> None:
        """Trigger a Live refresh when active."""
        if self._live:
            self._live.update(self.render(), refresh=True)

    def render(self) -> Layout:
        """Return the layout for the current state."""
        snapshot = self.viewmodel.snapshot()
        # Resize journal panel based on number of host/workload rows and
        # terminal height.
        row_count = max(1, snapshot.row_count)
        term_height = self.console.size.height if self.console.size else 40
        journal_height = dashboard_helpers.computed_journal_height(
            row_count, term_height
        )
        status_size = max(5, getattr(self.layout["status"], "size", 5))
        logs_height = max(6, term_height - journal_height - status_size - 2)
        self.layout["journal"].size = journal_height
        self.layout["status"].size = status_size
        self.layout["logs"].size = logs_height
        self._visible_log_lines = max(3, logs_height - 2)
        self.layout["journal"].update(self._render_journal(snapshot))
        self.layout["status"].update(self._render_status(snapshot))
        self.layout["logs"].update(self._render_logs(snapshot))
        return self.layout

    def _render_logs(self, snapshot: DashboardSnapshot) -> Panel:
        """Render the rolling log stream."""
        max_visible = getattr(self, "_visible_log_lines", self.max_log_lines)
        lines = self._visible_logs(max_visible)
        table = Table.grid(expand=True)
        table.add_column(ratio=1)
        table.add_column(justify="right", style=theme.LOG_TIMING_STYLE, width=14)
        if not lines:
            table.add_row(theme.empty_state("No live activity yet"), "")
        else:
            for line in lines:
                message, timing = dashboard_helpers.split_timing(line)
                table.add_row(message, timing)
        return Panel(
            table,
            title=theme.panel_title(
                "Activity Log",
                meta=f"mode: {self._log_mode} • L toggle",
                active=False,
            ),
            border_style=theme.RICH_BORDER_STYLE,
        )

    def _visible_logs(self, max_visible: int) -> list[str]:
        source = self.log_buffer if self._log_mode == "summary" else self.raw_log_buffer
        return source[-max_visible:]

    def _toggle_log_mode(self) -> None:
        self._log_mode = "all" if self._log_mode == "summary" else "summary"
        self.refresh()

    def _start_key_listener(self) -> None:
        if not self._supports_key_toggle():
            return
        if self._key_listener_thread and self._key_listener_thread.is_alive():
            return
        self._key_listener_stop.clear()
        self._key_listener_thread = threading.Thread(
            target=self._key_listener_loop,
            name="lb-dashboard-keys",
            daemon=True,
        )
        self._key_listener_thread.start()

    def _stop_key_listener(self) -> None:
        self._key_listener_stop.set()
        if self._key_listener_thread:
            self._key_listener_thread.join(timeout=1)
            self._key_listener_thread = None

    def _supports_key_toggle(self) -> bool:
        if os.name == "nt":
            return False
        if termios is None or tty is None:
            return False
        try:
            return sys.stdin.isatty()
        except Exception:
            return False

    def _key_listener_loop(self) -> None:
        fd = sys.stdin.fileno()
        old_attrs = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            while not self._key_listener_stop.is_set():
                ready, _, _ = select.select([fd], [], [], 0.1)
                if not ready:
                    continue
                chars = os.read(fd, 1)
                if chars in (b"l", b"L"):
                    self._toggle_log_mode()
        except Exception:
            return
        finally:
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)
            except Exception:
                pass

    def _empty_status_message(self) -> str:
        return "No active warnings"

    def _status_lines(
        self,
        snapshot: DashboardSnapshot,
        *,
        now: float | None = None,
        available_width: int | None = None,
    ) -> list[str]:
        status, detail = event_status_parts(
            self.event_source, self.last_event_ts, now=now
        )
        stream = "stream waiting" if status == "waiting" else f"stream live • {detail}"
        summary = [
            f"run {snapshot.run_id}",
            f"controller {self.controller_state}",
            stream,
        ]
        available_width = available_width or getattr(self.console.size, "width", 120) or 120
        if available_width >= 96:
            lines = [" • ".join(summary)]
        else:
            lines = [summary[0], summary[1], summary[2]]

        if self._warning_message and self._warning_expires_at and now is not None:
            if now < self._warning_expires_at:
                lines.append(self._warning_message)
            else:
                self._warning_expires_at = None
                self._warning_message = None

        if len(lines) == (1 if available_width >= 96 else 3):
            lines.append(self._empty_status_message())
        return lines

    def _render_status(self, snapshot: DashboardSnapshot) -> Panel:
        """Render controller/event status and transient warnings."""
        now = time.monotonic()
        lines = self._status_lines(
            snapshot,
            now=now,
            available_width=getattr(self.console.size, "width", 120) or 120,
        )
        rendered_lines: list[str] = []
        for idx, line in enumerate(lines):
            if line == self._empty_status_message():
                rendered_lines.append(theme.empty_state(line))
            elif idx == len(lines) - 1 and line == self._warning_message:
                rendered_lines.append(theme.warning_banner(line))
            elif line.startswith("controller "):
                rendered_lines.append(
                    theme.controller_state_line(line.removeprefix("controller "))
                )
            else:
                rendered_lines.append(line)
        return Panel(
            "\n".join(rendered_lines),
            title=theme.panel_title("Run Status", meta="control plane", active=False),
            border_style=theme.RICH_BORDER_STYLE,
        )

    def _render_journal(self, snapshot: DashboardSnapshot) -> Panel:
        table = Table(
            expand=True,
            box=None,
            padding=(0, 1),
            header_style=theme.DASHBOARD_HEADER_STYLE,
        )
        table.add_column("Host", style=theme.DASHBOARD_HOST_STYLE, width=18, no_wrap=True)
        table.add_column("Workload", width=20, no_wrap=True, overflow="ellipsis")
        table.add_column("State", justify="center", width=9, no_wrap=True)
        table.add_column("Prog", justify="left", width=12, no_wrap=True)
        table.add_column(
            "Action",
            style=theme.DASHBOARD_ACTION_STYLE,
            ratio=1,
            overflow="ellipsis",
            min_width=12,
        )

        for row in snapshot.rows:
            table.add_row(
                row.host,
                f"{row.workload} {theme.muted('•')} {row.intensity}",
                dashboard_helpers.style_status(row.status),
                dashboard_helpers.render_progress(row.progress),
                dashboard_helpers.render_action(row.current_action, row.last_rep_time),
            )

        return Panel(
            table,
            title=theme.panel_title("Run Journal", meta=snapshot.run_id),
            border_style=theme.RICH_BORDER_STYLE_ACTIVE,
        )

    def add_log(self, message: str) -> None:
        """Append a message to the log buffer."""
        if not message or not message.strip():
            return
        stripped = message.strip()
        self.raw_log_buffer.append(stripped)
        if self._rollup_helper.maybe_rollup(stripped):
            self._write_ui_log(stripped)
            self._trim_log_buffer()
            return
        self.log_buffer.append(stripped)
        self._write_ui_log(stripped)
        self._trim_log_buffer()

    def _write_ui_log(self, message: str) -> None:
        if not self.ui_log_file:
            return
        try:
            self.ui_log_file.write(message + "\n")
            self.ui_log_file.flush()
        except Exception:
            pass

    def _trim_log_buffer(self) -> None:
        trim_target = getattr(self, "_visible_log_lines", self.max_log_lines) * 5
        if len(self.log_buffer) > trim_target:
            del self.log_buffer[:-trim_target]
        if len(self.raw_log_buffer) > trim_target:
            del self.raw_log_buffer[:-trim_target]

    def mark_event(self, source: str) -> None:
        """Record that an event arrived from the given source (e.g., tcp/stdout)."""
        self.event_source = source or "unknown"
        self.last_event_ts = time.monotonic()

    def set_controller_state(self, state: str) -> None:
        """Update controller state label."""
        self.controller_state = state

    def set_warning(self, message: str, ttl: float = 10.0) -> None:
        """Show a transient warning banner for the given duration."""
        self._warning_message = message
        self._warning_expires_at = time.monotonic() + ttl

    def clear_warning(self) -> None:
        """Clear any active warning banner."""
        self._warning_message = None
        self._warning_expires_at = None


class RichDashboardFactory(DashboardFactory):
    def __init__(self, console: Console):
        self._console = console

    def create(
        self, viewmodel: DashboardViewModel, ui_log_file: IO[str] | None = None
    ) -> Dashboard:
        return RichDashboard(self._console, viewmodel, ui_log_file)
