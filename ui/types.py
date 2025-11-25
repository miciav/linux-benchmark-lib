from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol, Sequence


class ProgressHandle(Protocol):
    """Progress task handle for updating completion."""

    def update(self, completed: int) -> None:
        """Update the task with the absolute completed amount."""

    def finish(self) -> None:
        """Mark the task as finished and flush any pending output."""


class UIAdapter(Protocol):
    """Minimal interface for presentation concerns."""

    def show_info(self, message: str) -> None:
        """Render an informational message."""

    def show_warning(self, message: str) -> None:
        """Render a warning message."""

    def show_error(self, message: str) -> None:
        """Render an error message."""

    def show_success(self, message: str) -> None:
        """Render a success message."""

    def show_panel(self, message: str, title: str | None = None, border_style: str | None = None) -> None:
        """Render a block/panel container."""

    def show_rule(self, title: str) -> None:
        """Render a horizontal rule with a title."""

    def show_table(self, title: str, columns: Sequence[str], rows: list[Sequence[str]]) -> None:
        """Render a simple table."""

    def status(self, message: str) -> AbstractContextManager[None]:
        """Context manager that shows a status/spinner while work is running."""

    def create_progress(self, description: str, total: int) -> ProgressHandle:
        """Create a progress task."""
