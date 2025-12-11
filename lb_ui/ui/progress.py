"""Shared progress handle implementations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import IO

from lb_controller.ui_interfaces import ProgressHandle

try:
    from rich.progress import Progress, TaskID
    from rich.progress import BarColumn, TaskProgressColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn
except Exception:  # pragma: no cover - optional rich
    Progress = None  # type: ignore[misc]
    TaskID = int  # type: ignore[misc]


@dataclass
class RichProgressHandle(ProgressHandle):
    """Progress handle backed by rich.Progress."""

    description: str
    total: int
    progress: Progress
    task_id: TaskID
    finished: bool = False

    def update(self, completed: int) -> None:
        if self.finished:
            return
        clamped = min(completed, self.total)
        self.progress.update(self.task_id, completed=clamped)

    def finish(self) -> None:
        if self.finished:
            return
        self.progress.update(self.task_id, completed=self.total)
        self.progress.stop()
        self.finished = True


@dataclass
class StreamProgressHandle(ProgressHandle):
    """Lightweight progress tracker for headless mode."""

    description: str
    total: int
    stream: IO[str]
    last_written: int = 0

    def update(self, completed: int) -> None:
        completed = min(completed, self.total)
        if completed == self.last_written:
            return
        self.last_written = completed
        percent = int((completed / self.total) * 100) if self.total else 100
        self.stream.write(f"\r{self.description}: {percent}%")
        self.stream.flush()

    def finish(self) -> None:
        self.update(self.total)
        self.stream.write("\n")
        self.stream.flush()


def rich_progress(console) -> Progress:
    """Create a Rich Progress instance."""
    return Progress(
        TextColumn("[bold accent]{task.description}[/bold accent]"),
        BarColumn(bar_width=40, complete_style="accent", finished_style="accent"),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=True,
        expand=True,
    )
