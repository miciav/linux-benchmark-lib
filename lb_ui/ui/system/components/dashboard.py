"""Rich dashboard rendering for the run journal."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Dict, Iterable, List, Any, Optional
import time

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

# Ideally we should decouple this, but for now we reuse the domain objects
try:
    from lb_controller.journal import RunJournal, RunStatus, TaskState
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

class RichDashboard(Dashboard):
    """Render run plan and journal tables with Live refreshes."""

    def __init__(
        self,
        console: Console,
        plan_rows: List[Dict[str, str]],
        journal: RunJournal,
    ) -> None:
        self.console = console
        self.plan_rows = plan_rows
        self.journal = journal
        self.log_buffer: List[str] = []
        self.max_log_lines = 20
        self.layout = Layout()
        self.layout.split_column(
            Layout(name="journal"),
            Layout(name="logs"),
        )
        self._live: Live | None = None
        self.event_source: str = "waiting"
        self.last_event_ts: float | None = None
        self._intensity = {row.get("name"): row.get("intensity", "-") for row in plan_rows}

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
        logs_height = self._computed_log_height(journal_height, term_height)
        self.layout["journal"].size = journal_height
        self.layout["logs"].size = logs_height
        self._visible_log_lines = max(3, logs_height - 2)
        self.layout["journal"].update(self._render_journal())
        self.layout["logs"].update(self._render_logs())
        return self.layout

    def _render_logs(self) -> Panel:
        """Render the rolling log stream."""
        max_visible = getattr(self, "_visible_log_lines", self.max_log_lines)
        lines = self.log_buffer[-max_visible :]
        status = self._event_status_line()
        text = "\n".join([status] + lines) if status else "\n".join(lines)
        return Panel(
            text,
            title="[bold blue]Log Stream[/bold blue]",
            border_style="blue",
        )

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
        # Trim occasionally to avoid unbounded growth
        trim_target = getattr(self, "_visible_log_lines", self.max_log_lines) * 5
        if len(self.log_buffer) > trim_target:
            self.log_buffer = self.log_buffer[-trim_target :]

    def mark_event(self, source: str) -> None:
        """Record that an event arrived from the given source (e.g., tcp/stdout)."""
        self.event_source = source or "unknown"
        self.last_event_ts = time.monotonic()

    def _event_status_line(self) -> str:
        if self.last_event_ts is None:
            return "[dim]Event stream: waiting[/dim]"
        age = time.monotonic() - self.last_event_ts
        freshness = "just now" if age < 1.0 else f"{age:.1f}s ago"
        return f"[green]Event stream: live ({self.event_source}, {freshness})[/green]"

    def _target_repetitions(self) -> int:
        from_metadata = self.journal.metadata.get("repetitions")
        if isinstance(from_metadata, int) and from_metadata > 0:
            return from_metadata
        if not self.journal.tasks:
             return 0
        reps = [task.repetition for task in self.journal.tasks.values()]
        return max(reps) if reps else 0

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
        status, _ = self._summarize_progress(tasks, target_reps)
        return status

    @staticmethod
    def _summarize_progress(
        tasks: Dict[int, TaskState], target_reps: int
    ) -> tuple[str, str]:
        total = target_reps or len(tasks)
        completed = sum(
            1
            for task in tasks.values()
            if task.status in (RunStatus.COMPLETED, RunStatus.SKIPPED, RunStatus.FAILED)
        )
        running = any(task.status == RunStatus.RUNNING for task in tasks.values())
        failed = any(task.status == RunStatus.FAILED for task in tasks.values())
        skipped = tasks and all(task.status == RunStatus.SKIPPED for task in tasks.values())

        if failed:
            status = "[red]failed[/red]"
        elif running:
            status = "[yellow]running[/yellow]"
        elif skipped:
            status = "[dim]skipped[/dim]"
        elif total and completed >= total:
            status = "[green]done[/green]"
        elif completed > 0:
            status = "[yellow]partial[/yellow]"
        else:
            status = "[dim]pending[/dim]"

        progress = f"{completed}/{total}" if total else "0/0"
        return status, progress

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
        
    def create(self, plan: list[Dict[str, Any]], journal: Any) -> Dashboard:
        return RichDashboard(self._console, plan, journal)
