"""Rich dashboard rendering for the run journal."""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import IO, List

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from lb_ui.presenters.dashboard import (
    DashboardSnapshot,
    DashboardViewModel,
    event_status_line,
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
        self.controller_state: str = "init"
        self._warning_message: str | None = None
        self._warning_expires_at: float | None = None

    @contextmanager
    def live(self):
        """Context manager that drives Live updates."""
        if self._live is not None:
            yield self
            return
        with Live(
            self.render(),
            console=self.console,
            refresh_per_second=4,
            screen=True,
        ) as live:
            self._live = live
            try:
                yield self
            finally:
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
        self.layout["status"].update(self._render_status())
        self.layout["logs"].update(self._render_logs(snapshot))
        return self.layout

    def _render_logs(self, snapshot: DashboardSnapshot) -> Panel:
        """Render the rolling log stream."""
        max_visible = getattr(self, "_visible_log_lines", self.max_log_lines)
        lines = self.log_buffer[-max_visible :]
        table = Table.grid(expand=True)
        table.add_column(ratio=1)
        table.add_column(justify="right", style=theme.LOG_TIMING_STYLE, width=14)
        for line in lines:
            message, timing = dashboard_helpers.split_timing(line)
            table.add_row(message, timing)
        return Panel(
            table,
            title=theme.panel_title(snapshot.log_metadata.title),
            border_style=theme.RICH_BORDER_STYLE,
        )

    def _render_status(self) -> Panel:
        """Render controller/event status and transient warnings."""
        now = time.monotonic()
        warning = None
        if self._warning_expires_at and now < self._warning_expires_at:
            warning = self._warning_message
        elif self._warning_expires_at and now >= self._warning_expires_at:
            self._warning_expires_at = None
            self._warning_message = None
        lines = []
        lines.append(
            event_status_line(self.event_source, self.last_event_ts, now=now)
        )
        lines.append(theme.controller_state_line(self.controller_state))
        if warning:
            lines.append(theme.warning_banner(warning))
        else:
            lines.append("")
        return Panel(
            "\n".join(lines),
            title=theme.panel_title("Status"),
            border_style=theme.RICH_BORDER_STYLE,
        )

    def _render_journal(self, snapshot: DashboardSnapshot) -> Panel:
        table = Table(expand=True, box=None, padding=(0, 1))
        table.add_column("Host", style=theme.DASHBOARD_HOST_STYLE, width=24)
        table.add_column("Workload", width=10)
        table.add_column("Intensity", width=10)
        table.add_column("Status", justify="center", width=10)
        table.add_column("Progress", justify="center", width=10)
        table.add_column("Current Action", style=theme.DASHBOARD_ACTION_STYLE)
        table.add_column("Last Rep Time", justify="right", width=12)

        for row in snapshot.rows:
            table.add_row(
                row.host,
                row.workload,
                str(row.intensity),
                dashboard_helpers.style_status(row.status),
                row.progress,
                row.current_action,
                row.last_rep_time,
            )

        return Panel(
            table,
            title=theme.panel_title(f"Run Journal (ID: {snapshot.run_id})"),
            border_style=theme.RICH_BORDER_STYLE,
        )

    def add_log(self, message: str) -> None:
        """Append a message to the log buffer."""
        if not message or not message.strip():
            return
        stripped = message.strip()
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
