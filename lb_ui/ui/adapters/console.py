"""Rich-based console adapter used for all TTY output."""

from __future__ import annotations

import shutil
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from typing import IO, Sequence, Any

from rich.console import Console
from rich.panel import Panel
from rich.progress import TaskID
from rich.table import Table
from rich.theme import Theme

from lb_controller.ui_interfaces import DashboardHandle
from lb_ui.ui.dashboard import RunDashboard, StreamDashboard
from lb_ui.ui.progress import RichProgressHandle, rich_progress
from lb_ui.ui.prompts import prompt_multipass
from lb_ui.ui.utils import format_table
from lb_ui.ui.viewmodels import plan_rows
from lb_controller.ui_interfaces import UIAdapter

THEME = Theme(
    {
        "info": "cyan",
        "warning": "yellow",
        "error": "red",
        "success": "green",
        "accent": "#3ea6ff",
    }
)


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
        # Keep tables within the visible console width and fold long cells.
        term_width = 0
        try:
            term_width = self.console.size.width
        except Exception:
            pass

        if not term_width:
            try:
                term_width = shutil.get_terminal_size(fallback=(100, 24)).columns
            except Exception:
                pass

        table_width = max(60, term_width - 2) if term_width and term_width > 0 else None

        table = Table(
            title=f"[b]{title}[/b]",
            border_style="accent",
            header_style="bold white",
            row_styles=("", "dim"),
            expand=table_width is None,
            width=table_width,
        )
        for column in columns:
            table.add_column(column, overflow="fold")
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

    def create_progress(self, description: str, total: int):
        normalized_total = max(total, 1)
        progress = rich_progress(self.console)
        task_id: TaskID = progress.add_task(description, total=normalized_total)
        progress.start()
        return RichProgressHandle(
            description=description,
            total=normalized_total,
            progress=progress,
            task_id=task_id,
        )

    def create_dashboard(self, plan: list[dict[str, Any]], journal: Any, ui_log_file: IO[str] | None = None) -> DashboardHandle:
        """Create a run dashboard."""
        if self.console.is_interactive:
            return RunDashboard(self.console, plan, journal, ui_log_file)  # type: ignore
        return StreamDashboard(ui_log_file)

    def prompt_multipass_scenario(self, options: list[str], default_level: str) -> tuple[str, str] | None:
        """Prompt user for multipass scenario selection."""
        return prompt_multipass(options, self, default_level=default_level)
