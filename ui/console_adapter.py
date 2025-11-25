from __future__ import annotations

"""Rich-based console adapter used for all TTY output."""

import sys
from contextlib import contextmanager
from dataclasses import dataclass
from typing import IO, Sequence

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table
from rich.theme import Theme

from .types import ProgressHandle, UIAdapter

THEME = Theme(
    {
        "info": "cyan",
        "warning": "yellow",
        "error": "red",
        "success": "green",
        "accent": "#3ea6ff",
    }
)


@dataclass
class _RichProgress(ProgressHandle):
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


class ConsoleUIAdapter(UIAdapter):
    """ANSI-friendly output with Rich tables and progress bars."""

    def __init__(self, stream: IO[str] | None = None):
        self.console = Console(
            theme=THEME,
            file=stream or sys.stdout,
            highlight=False,
            soft_wrap=True,
        )

    def show_info(self, message: str) -> None:
        self.console.print(message, style="info")

    def show_warning(self, message: str) -> None:
        self.console.print(message, style="warning")

    def show_error(self, message: str) -> None:
        self.console.print(message, style="error")

    def show_success(self, message: str) -> None:
        self.console.print(message, style="success")

    def show_panel(self, message: str, title: str | None = None, border_style: str | None = None) -> None:
        panel = Panel(message, title=title, border_style=border_style or "accent", expand=True)
        self.console.print(panel)

    def show_rule(self, title: str) -> None:
        self.console.rule(f"[b]{title}[/b]", style="accent")

    def show_table(self, title: str, columns: Sequence[str], rows: list[Sequence[str]]) -> None:
        table = Table(
            title=f"[b]{title}[/b]",
            border_style="accent",
            header_style="bold white",
            row_styles=("", "dim"),
            expand=True,
        )
        for column in columns:
            table.add_column(column)
        for row in rows:
            table.add_row(*[str(cell) for cell in row])
        self.console.print(table)

    @contextmanager
    def status(self, message: str):
        with self.console.status(f"[accent]{message}...[/accent]", spinner="dots") as status:
            try:
                yield
                status.update(f"[success]Done.[/success]")
            except Exception:
                status.update(f"[error]Failed.[/error]")
                raise

    def create_progress(self, description: str, total: int) -> ProgressHandle:
        normalized_total = max(total, 1)
        progress = Progress(
            TextColumn("[bold accent]{task.description}[/bold accent]"),
            BarColumn(bar_width=40, complete_style="accent", finished_style="accent"),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=self.console,
            transient=True,
            expand=True,
        )
        task_id = progress.add_task(description, total=normalized_total)
        progress.start()
        return _RichProgress(
            description=description,
            total=normalized_total,
            progress=progress,
            task_id=task_id,
        )
