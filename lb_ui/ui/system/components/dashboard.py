"""Rich dashboard rendering for the run journal."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Dict, Iterable, List, Any, IO
import time

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

# Ideally we should decouple this, but for now we reuse the domain objects
try:
    from lb_controller.api import RunJournal, RunStatus, TaskState
except ImportError:
    # Fallback for strict isolation if needed, but practically we need these
    class RunStatus:
        RUNNING = "running"
        COMPLETED = "completed"
        FAILED = "failed"
        SKIPPED = "skipped"
        PENDING = "pending"
    TaskState = Any
    RunJournal = Any

from lb_ui.ui.system.protocols import Dashboard, DashboardFactory
from lb_ui import viewmodels


class RichDashboard(Dashboard):
    """Render run plan and journal tables with Live refreshes."""

    def __init__(
        self,
        console: Console,
        plan_rows: List[Dict[str, str]],
        journal: RunJournal,
        ui_log_file: IO[str] | None = None,
    ) -> None:
        self.console = console
        self.plan_rows = plan_rows
        self.journal = journal
        self.log_buffer: List[str] = []
        self.max_log_lines = 20
        self.layout = Layout()
        self.layout.split_column(
            Layout(name="journal"),
            Layout(name="status", size=5, minimum_size=5),
            Layout(name="logs"),
        )
        self._live: Live | None = None
        self.event_source: str = "waiting"
        self.last_event_ts: float | None = None
        self._intensity = {row.get("name"): row.get("intensity", "-") for row in plan_rows}
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
        # Resize journal panel based on number of host/workload rows and terminal height.
        row_count = max(1, sum(1 for _ in self._unique_pairs()))
        term_height = self.console.size.height if self.console.size else 40
        journal_height = self._computed_journal_height(row_count, term_height)
        status_size = max(5, getattr(self.layout["status"], "size", 5))
        logs_height = max(6, term_height - journal_height - status_size - 2)
        self.layout["journal"].size = journal_height
        self.layout["status"].size = status_size
        self.layout["logs"].size = logs_height
        self._visible_log_lines = max(3, logs_height - 2)
        self.layout["journal"].update(self._render_journal())
        self.layout["status"].update(self._render_status())
        self.layout["logs"].update(self._render_logs())
        return self.layout

    def _render_logs(self) -> Panel:
        """Render the rolling log stream."""
        max_visible = getattr(self, "_visible_log_lines", self.max_log_lines)
        lines = self.log_buffer[-max_visible :]
        text = "\n".join(lines)
        return Panel(text, title="[bold blue]Log Stream[/bold blue]", border_style="blue")

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
        lines.append(self._event_status_line())
        lines.append(f"[cyan]Controller state:[/cyan] {self.controller_state}")
        if warning:
            lines.append(f"[bold yellow]{warning}[/bold yellow]")
        else:
            lines.append("")
        return Panel("\n".join(lines), title="[bold blue]Status[/bold blue]", border_style="blue")

    def _render_journal(self) -> Panel:
        table = Table(expand=True, box=None, padding=(0, 1))
        table.add_column("Host", style="bold cyan", width=24)
        table.add_column("Workload", width=10)
        table.add_column("Intensity", width=10)
        table.add_column("Status", justify="center", width=10)
        table.add_column("Progress", justify="center", width=10)
        table.add_column("Current Action", style="dim italic")
        table.add_column("Last Rep Time", justify="right", width=12)

        for host, workload in self._unique_pairs():
            intensity = self._intensity.get(workload, "-")
            row: List[str] = [host, workload, str(intensity)]
            tasks = self._tasks_for(host, workload)
            status = self._aggregate_status(tasks)
            active_action = ""
            # Need to handle tasks dict values which might be objects or dicts depending on where journal comes from
            # But usually it's TaskState objects.
            running_task = next(
                (task for task in tasks.values() if task.status == RunStatus.RUNNING),
                None,
            )
            if running_task:
                active_action = running_task.current_action or "Running..."

            started = self._started_repetitions(tasks)
            # total = max(self._max_repetitions(), len(tasks)) or 0
            # Better to rely on tasks length or journal metadata if available
            # self._target_repetitions() handles it
            target = self._target_repetitions()
            total = target if target > 0 else (len(tasks) or 1)

            last_duration = self._latest_duration(tasks)

            row.extend([
                status,
                f"{started}/{total}",
                active_action,
                last_duration,
            ])
            table.add_row(*row)

        return Panel(
            table,
            title=f"[bold blue]Run Journal (ID: {self.journal.run_id})[/bold blue]",
            border_style="blue",
        )

    def add_log(self, message: str) -> None:
        """Append a message to the log buffer."""
        if not message or not message.strip():
            return
        self.log_buffer.append(message.strip())
        if self.ui_log_file:
            try:
                self.ui_log_file.write(message.strip() + "\n")
                self.ui_log_file.flush()
            except Exception:
                pass
        # Trim occasionally to avoid unbounded growth
        trim_target = getattr(self, "_visible_log_lines", self.max_log_lines) * 5
        if len(self.log_buffer) > trim_target:
            self.log_buffer = self.log_buffer[-trim_target :]

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

    def _event_status_line(self) -> str:
        if self.last_event_ts is None:
            return "[dim]Event stream: waiting[/dim]"
        age = time.monotonic() - self.last_event_ts
        freshness = "just now" if age < 1.0 else f"{age:.1f}s ago"
        return f"[green]Event stream: live ({self.event_source}, {freshness})[/green]"

    def _target_repetitions(self) -> int:
        return viewmodels.target_repetitions(self.journal)

    def _unique_pairs(self) -> Iterable[tuple[str, str]]:
        seen = set()
        for task in self.journal.tasks.values():
            key = (task.host, task.workload)
            if key in seen:
                continue
            seen.add(key)
            yield key

    def _tasks_for(self, host: str, workload: str) -> Dict[int, TaskState]:
        return {
            task.repetition: task
            for task in self.journal.tasks.values()
            if task.host == host and task.workload == workload
        }

    def _aggregate_status(self, tasks: Dict[int, TaskState]) -> str:
        """Summarize a workload's status across repetitions."""
        target_reps = self._target_repetitions()
        status, _ = viewmodels.summarize_progress(tasks, target_reps)
        return self._style_status(status)

    @staticmethod
    def _style_status(status: str) -> str:
        return {
            "failed": "[red]failed[/red]",
            "running": "[yellow]running[/yellow]",
            "skipped": "[dim]skipped[/dim]",
            "done": "[green]done[/green]",
            "partial": "[yellow]partial[/yellow]",
            "pending": "[dim]pending[/dim]",
        }.get(status, status)

    def _started_repetitions(self, tasks: Dict[int, TaskState]) -> int:
        return sum(1 for task in tasks.values() if task.status != RunStatus.PENDING)

    def _latest_duration(self, tasks: Dict[int, TaskState]) -> str:
        latest = None
        for task in tasks.values():
            if task.finished_at:
                if latest is None or task.finished_at > latest.finished_at:
                    latest = task
        if latest and latest.duration_seconds is not None:
            return f"{latest.duration_seconds:.1f}s"
        return ""

    def _computed_journal_height(self, row_count: int, term_height: int) -> int:
        """Pick a journal height that leaves room for logs."""
        min_height = min(30, max(10, row_count + 5))
        log_min = 6
        available = max(10, term_height - log_min)
        return min(available, min_height)

    def _computed_log_height(self, journal_height: int, term_height: int) -> int:
        """Assign remaining height to logs without hard caps."""
        log_min = 6
        padding = 2
        remaining = max(log_min, term_height - journal_height - padding)
        return remaining

class RichDashboardFactory(DashboardFactory):
    def __init__(self, console: Console):
        self._console = console
        
    def create(self, plan: list[Dict[str, Any]], journal: Any, ui_log_file: IO[str] | None = None) -> Dashboard:
        return RichDashboard(self._console, plan, journal, ui_log_file)
