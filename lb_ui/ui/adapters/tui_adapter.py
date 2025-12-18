from typing import Any, IO, Sequence
from contextlib import contextmanager, AbstractContextManager
import threading
import queue

from lb_controller.ui_interfaces import UIAdapter, DashboardHandle, ProgressHandle
from lb_ui.ui.system.protocols import UI
from lb_ui.ui.system.models import TableModel, PickItem

class TUIAdapter(UIAdapter):
    """Adapts the new UI Facade to the old UIAdapter protocol for Controller compatibility."""

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
        l_items = [PickItem(id=l, title=l) for l in levels]
        level_sel = self.tui.picker.pick_one(l_items, title="Select Intensity", query_hint=default_level)
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


class ThreadedDashboardHandle(DashboardHandle):
    """Run the dashboard rendering loop in its own thread, consuming queued events."""

    def __init__(self, inner: DashboardHandle):
        self._inner = inner
        self._queue: queue.Queue[tuple[str, tuple, dict] | None] = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @contextmanager
    def live(self) -> AbstractContextManager[None]:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="lb-dashboard-thread", daemon=True)
        self._thread.start()
        try:
            yield self
        finally:
            self._stop.set()
            self._queue.put(None)
            if self._thread:
                self._thread.join(timeout=2)
                self._thread = None

    def _run(self) -> None:
        with self._inner.live():
            while not self._stop.is_set():
                try:
                    item = self._queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                if item is None:
                    break
                method, args, kwargs = item
                try:
                    getattr(self._inner, method)(*args, **kwargs)
                    if method != "refresh":
                        self._inner.refresh()
                except Exception:
                    continue

    def add_log(self, line: str) -> None:
        self._queue.put(("add_log", (line,), {}))

    def refresh(self) -> None:
        self._queue.put(("refresh", tuple(), {}))

    def mark_event(self, source: str) -> None:
        self._queue.put(("mark_event", (source,), {}))

    def set_warning(self, message: str, ttl: float = 10.0) -> None:
        self._queue.put(("set_warning", (message,), {"ttl": ttl}))

    def clear_warning(self) -> None:
        self._queue.put(("clear_warning", tuple(), {}))

    def set_controller_state(self, state: str) -> None:
        self._queue.put(("set_controller_state", (state,), {}))
