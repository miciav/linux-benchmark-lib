"""No-op implementation of UIAdapter for headless execution."""

from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext
from typing import Any, Sequence

from lb_runner.interfaces import DashboardHandle, ProgressHandle, UIAdapter


class NoOpProgressHandle(ProgressHandle):
    """No-op progress handle."""

    def update(self, completed: int) -> None:
        pass

    def finish(self) -> None:
        pass


class NoOpDashboardHandle(DashboardHandle):
    """No-op dashboard handle."""

    def live(self) -> AbstractContextManager[None]:
        return nullcontext()

    def add_log(self, line: str) -> None:
        pass

    def refresh(self) -> None:
        pass

    def mark_event(self, source: str) -> None:
        pass


class NoOpUIAdapter(UIAdapter):
    """No-op UI adapter that discards all output."""

    def show_info(self, message: str) -> None:
        pass

    def show_warning(self, message: str) -> None:
        pass

    def show_error(self, message: str) -> None:
        pass

    def show_success(self, message: str) -> None:
        pass

    def show_panel(self, message: str, title: str | None = None, border_style: str | None = None) -> None:
        pass

    def show_rule(self, title: str) -> None:
        pass

    def show_table(self, title: str, columns: Sequence[str], rows: list[Sequence[str]]) -> None:
        pass

    def status(self, message: str) -> AbstractContextManager[None]:
        return nullcontext()

    def create_progress(self, description: str, total: int) -> ProgressHandle:
        return NoOpProgressHandle()

    def create_dashboard(self, plan: list[dict[str, Any]], journal: Any) -> DashboardHandle:
        return NoOpDashboardHandle()

    def prompt_multipass_scenario(self, options: list[str], default_level: str) -> tuple[str, str] | None:
        return None