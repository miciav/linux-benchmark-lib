from typing import Any, IO, Sequence
from contextlib import contextmanager, AbstractContextManager

from lb_app.api import UIAdapter, DashboardHandle, ProgressHandle
from lb_ui.tui.system.components.dashboard_adapter import DashboardAdapter
from lb_ui.tui.system.protocols import UI, Dashboard
from lb_ui.tui.system.models import TableModel, PickItem

class TUIAdapter(UIAdapter):
    """Adapts the UI facade to the app-level UIAdapter protocol."""

    def __init__(self, tui: UI):
        self.tui = tui

    def show_info(self, message: str) -> None:
        self.tui.present.info(message)

    def show_warning(self, message: str) -> None:
        self.tui.present.warning(message)

    def show_error(self, message: str) -> None:
        self.tui.present.error(message)

    def show_success(self, message: str) -> None:
        self.tui.present.success(message)

    def show_panel(self, message: str, title: str | None = None, border_style: str | None = None) -> None:
        self.tui.present.panel(message, title, border_style)

    def show_rule(self, title: str) -> None:
        self.tui.present.rule(title)

    def show_table(self, title: str, columns: Sequence[str], rows: list[Sequence[str]]) -> None:
        model = TableModel(title=title, columns=list(columns), rows=[list(r) for r in rows])
        self.tui.tables.show(model)

    def status(self, message: str) -> AbstractContextManager[None]:
        return self.tui.progress.status(message)

    def create_progress(self, description: str, total: int) -> ProgressHandle:
        # TODO: Implement proper progress mapping if needed.
        # For now, return a no-op or simple wrapper if TUI exposes it.
        # The prompt didn't specify Progress component in detail beyond 'status'.
        return _NoOpProgressHandle()

    def create_dashboard(self, plan: list[dict[str, Any]], journal: Any, ui_log_file: IO[str] | None = None) -> DashboardHandle:
        # Use the TUI's dashboard factory
        # We assume the Dashboard protocol from UI system matches or is compatible with DashboardHandle
        # They both have live(), add_log(), refresh(), mark_event()
        return ThreadedDashboardHandle(self.tui.dashboard.create(plan, journal, ui_log_file))

    def prompt_multipass_scenario(self, options: list[str], default_level: str) -> tuple[str, str] | None:
        # Use TUI picker!
        items = [PickItem(id=o, title=o) for o in options]
        selection = self.tui.picker.pick_one(items, title="Select Multipass Scenario")
        if not selection:
            return None
        
        # Then prompt for intensity
        levels = ["low", "medium", "high"]
        # Use simple prompt or picker? Picker is better.
        level_items = [PickItem(id=level_name, title=level_name) for level_name in levels]
        level_sel = self.tui.picker.pick_one(
            level_items,
            title="Select Intensity",
            query_hint=default_level,
        )
        level = level_sel.id if level_sel else default_level
        
        return selection.id, level

class _NoOpProgressHandle(ProgressHandle):
    def update(self, completed: int) -> None: pass
    def finish(self) -> None: pass

class _NoOpDashboardHandle(DashboardHandle):
    def live(self) -> AbstractContextManager[None]: return contextmanager(lambda: (yield))()
    def add_log(self, line: str) -> None: pass
    def refresh(self) -> None: pass
    def mark_event(self, source: str) -> None: pass


class ThreadedDashboardHandle(DashboardAdapter):
    """Run the dashboard rendering loop in its own thread."""

    def __init__(self, inner: Dashboard):
        super().__init__(inner, threaded=True)
