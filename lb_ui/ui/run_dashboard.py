from __future__ import annotations

"""Rich dashboard rendering for the run journal."""

from contextlib import contextmanager
from typing import Dict, Iterable, List
import time

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from lb_controller.journal import RunJournal, RunStatus, TaskState


class RunDashboard:
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
            Layout(name="logs", size=self.max_log_lines + 2),
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
        self.layout["journal"].update(self._render_journal())
        self.layout["logs"].update(self._render_logs())
        return self.layout

    def _render_logs(self) -> Panel:
        """Render the rolling log stream."""
        lines = self.log_buffer[-self.max_log_lines :]
        status = self._event_status_line()
        text = "\n".join([status] + lines) if status else "\n".join(lines)
        return Panel(
            text,
            title="[bold]Log Stream[/bold]",
            border_style="bright_black",
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

        target_reps = self._target_repetitions()

        for host, workload in self._unique_pairs():
            intensity = self._intensity.get(workload, "-")
            row: List[str] = [host, workload, str(intensity)]
            tasks = self._tasks_for(host, workload)
            status = self._aggregate_status(tasks)
            active_action = ""
            running_task = next(
                (task for task in tasks.values() if task.status == RunStatus.RUNNING),
                None,
            )
            if running_task:
                active_action = running_task.current_action or "Running..."

            started = self._started_repetitions(tasks)
            completed = self._completed_repetitions(tasks)
            total = max(self._max_repetitions(), len(tasks)) or 0
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
            title=f"[bold]Run Journal (ID: {self.journal.run_id})[/bold]",
            border_style="bright_black",
        )

    def add_log(self, message: str) -> None:
        """Append a message to the log buffer."""
        if not message or not message.strip():
            return
        self.log_buffer.append(message.strip())
        # Trim occasionally to avoid unbounded growth
        if len(self.log_buffer) > self.max_log_lines * 5:
            self.log_buffer = self.log_buffer[-self.max_log_lines * 5 :]

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

    def _max_repetitions(self) -> int:
        """Return the highest repetition index observed in the journal."""
        if not self.journal.tasks:
            return 0
        return max(task.repetition for task in self.journal.tasks.values())

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
            status = "[red]✘ Fail[/red]"
        elif running:
            status = "[yellow]⟳ Run[/yellow]"
        elif skipped:
            status = "[cyan]Skip[/cyan]"
        elif total and completed >= total:
            status = "[green]✔ Done[/green]"
        elif completed > 0:
            status = "[cyan]▶ Partial[/cyan]"
        else:
            status = "[dim]Wait[/dim]"

        progress = f"{completed}/{total or '?'}"
        return status, progress

    @staticmethod
    def _completed_repetitions(tasks: Dict[int, TaskState]) -> int:
        return sum(1 for task in tasks.values() if task.status in {RunStatus.COMPLETED, RunStatus.SKIPPED})

    @staticmethod
    def _started_repetitions(tasks: Dict[int, TaskState]) -> int:
        """Count repetitions that have begun (running, completed, failed, or skipped)."""
        started_statuses = {
            RunStatus.RUNNING,
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.SKIPPED,
        }
        return sum(1 for task in tasks.values() if task.status in started_statuses)

    @staticmethod
    def _latest_duration(tasks: Dict[int, TaskState]) -> str:
        """Return the most recent duration (s) for any repetition."""
        if not tasks:
            return "-"
        durations = [t.duration_seconds for t in tasks.values() if t.duration_seconds]
        if not durations:
            return "-"
        latest = durations[-1]
        return f"{latest:.1f}s"


class NoopDashboard:
    """Placeholder used when no TTY is available."""

    @contextmanager
    def live(self):
        yield self

    def refresh(self) -> None:  # noqa: D401 - simple no-op
        """No-op refresh."""
        return

    def add_log(self, _: str) -> None:
        """No-op log appender."""
        return
