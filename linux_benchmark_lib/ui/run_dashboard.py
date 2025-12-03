from __future__ import annotations

"""Rich dashboard rendering for the run journal."""

from contextlib import contextmanager
from typing import Dict, Iterable, List

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from ..journal import RunJournal, RunStatus, TaskState


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
            Layout(name="plan", size=self._plan_height()),
            Layout(name="journal"),
            Layout(name="logs", size=self.max_log_lines + 2),
        )
        self._live: Live | None = None

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
        # Resize plan dynamically so multiple workloads stay visible.
        self.layout["plan"].size = self._plan_height()
        self.layout["plan"].update(self._render_plan())
        self.layout["journal"].update(self._render_journal())
        self.layout["logs"].update(self._render_logs())
        return self.layout

    def _render_plan(self) -> Panel:
        table = Table(
            show_edge=True,
            expand=True,
            border_style="cyan",
            header_style="bold white",
        )
        table.add_column("Workload")
        table.add_column("Plugin", style="cyan")
        table.add_column("Intensity")
        table.add_column("Configuration")
        table.add_column("Repetitions", justify="center")
        table.add_column("Status", style="green")

        for row in self.plan_rows:
            table.add_row(
                row.get("name", ""),
                row.get("plugin", ""),
                row.get("intensity", ""),
                row.get("details", ""),
                row.get("repetitions", ""),
                row.get("status", ""),
            )

        return Panel(
            table,
            title="Run Plan",
            border_style="cyan",
        )

    def _render_logs(self) -> Panel:
        """Render the rolling log stream."""
        lines = self.log_buffer[-self.max_log_lines :]
        text = "\n".join(lines)
        return Panel(
            text,
            title="[bold]Log Stream[/bold]",
            border_style="bright_black",
        )

    def _render_journal(self) -> Panel:
        table = Table(expand=True, box=None, padding=(0, 1))
        table.add_column("Host", style="bold cyan", width=24)
        table.add_column("Workload", width=10)
        table.add_column("Run", justify="center", width=12)
        table.add_column("Current Action", style="dim italic")

        target_reps = self._target_repetitions()

        for host, workload in self._unique_pairs():
            row: List[str] = [host, workload]
            tasks = self._tasks_for(host, workload)
            active_action = ""
            status_text, progress = self._summarize_progress(tasks, target_reps)
            row.append(f"{status_text}\n[dim]{progress}[/dim]")

            running_task = next(
                (t for t in tasks.values() if t.status == RunStatus.RUNNING),
                None,
            )
            if running_task:
                active_action = running_task.current_action or "Running..."

            row.append(active_action)
            table.add_row(*row)

        return Panel(
            table,
            title=f"[bold]Run Journal (ID: {self.journal.run_id})[/bold]",
            border_style="bright_black",
        )

    def _plan_height(self) -> int:
        """Compute a plan section height that fits all rows."""
        return max(6, len(self.plan_rows) + 6)

    def add_log(self, message: str) -> None:
        """Append a message to the log buffer."""
        if not message or not message.strip():
            return
        self.log_buffer.append(message.strip())
        # Trim occasionally to avoid unbounded growth
        if len(self.log_buffer) > self.max_log_lines * 5:
            self.log_buffer = self.log_buffer[-self.max_log_lines * 5 :]

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
