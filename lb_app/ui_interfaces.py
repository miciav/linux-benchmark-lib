"""App-level UI contracts and no-op implementations."""

from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext
from typing import Any, Protocol, Sequence, IO


class DashboardHandle(Protocol):
    """Handle for a live dashboard visualization."""

    def live(self) -> AbstractContextManager[None]:
        """Return a context manager that keeps the dashboard live."""

    def add_log(self, line: str) -> None:
        """Add a log line to the dashboard."""

    def refresh(self) -> None:
        """Trigger a refresh of the dashboard."""

    def mark_event(self, source: str) -> None:
        """Mark an event occurrence (e.g., visual flash)."""


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

    def create_dashboard(self, plan: list[dict[str, Any]], journal: Any, ui_log_file: IO[str] | None = None) -> DashboardHandle:
        """Create a run dashboard."""

    def prompt_multipass_scenario(self, options: list[str], default_level: str) -> tuple[str, str] | None:
        """Prompt user for multipass scenario selection."""


class NoOpProgressHandle(ProgressHandle):
    """No-op progress handle."""

    def update(self, completed: int) -> None:  # pragma: no cover - trivial
        pass

    def finish(self) -> None:  # pragma: no cover - trivial
        pass


class NoOpDashboardHandle(DashboardHandle):
    """No-op dashboard handle."""

    def live(self) -> AbstractContextManager[None]:
        return nullcontext()

    def add_log(self, line: str) -> None:  # pragma: no cover - trivial
        pass

    def refresh(self) -> None:  # pragma: no cover - trivial
        pass

    def mark_event(self, source: str) -> None:  # pragma: no cover - trivial
        pass


class NoOpUIAdapter(UIAdapter):
    """No-op UI adapter that discards all output."""

    def show_info(self, message: str) -> None:  # pragma: no cover - trivial
        pass

    def show_warning(self, message: str) -> None:  # pragma: no cover - trivial
        pass

    def show_error(self, message: str) -> None:  # pragma: no cover - trivial
        pass

    def show_success(self, message: str) -> None:  # pragma: no cover - trivial
        pass

    def show_panel(self, message: str, title: str | None = None, border_style: str | None = None) -> None:  # pragma: no cover - trivial
        pass

    def show_rule(self, title: str) -> None:  # pragma: no cover - trivial
        pass

    def show_table(self, title: str, columns: Sequence[str], rows: list[Sequence[str]]) -> None:  # pragma: no cover - trivial
        pass

    def status(self, message: str) -> AbstractContextManager[None]:
        return nullcontext()

    def create_progress(self, description: str, total: int) -> ProgressHandle:
        return NoOpProgressHandle()

    def create_dashboard(self, plan: list[dict[str, Any]], journal: Any, ui_log_file: IO[str] | None = None) -> DashboardHandle:
        return NoOpDashboardHandle()

    def prompt_multipass_scenario(self, options: list[str], default_level: str) -> tuple[str, str] | None:  # pragma: no cover - trivial
        return None
