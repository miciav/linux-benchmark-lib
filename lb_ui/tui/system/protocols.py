from contextlib import nullcontext
from typing import Any, Protocol, Sequence, ContextManager, IO
from lb_ui.tui.system.models import TableModel, PickItem, SelectionNode

class TablePresenter(Protocol):
    def show(self, table: TableModel) -> None: ...

class Picker(Protocol):
    def pick_one(
        self,
        items: Sequence[PickItem],
        *,
        title: str,
        query_hint: str = ""
    ) -> PickItem | None: ...

    def pick_many(
        self,
        items: Sequence[PickItem],
        *,
        title: str,
        query_hint: str = ""
    ) -> list[PickItem] | None: ...

class HierarchicalPicker(Protocol):
    def pick_one(
        self,
        root: SelectionNode,
        *,
        title: str
    ) -> SelectionNode | None: ...

class PresenterSink(Protocol):
    def emit(self, level: str, message: str) -> None: ...
    def emit_panel(self, message: str, title: str | None, border_style: str | None) -> None: ...
    def emit_rule(self, title: str) -> None: ...


class Presenter:
    def __init__(self, sink: PresenterSink) -> None:
        self._sink = sink

    def info(self, message: str) -> None:
        self._sink.emit("info", message)

    def warning(self, message: str) -> None:
        self._sink.emit("warning", message)

    def error(self, message: str) -> None:
        self._sink.emit("error", message)

    def success(self, message: str) -> None:
        self._sink.emit("success", message)

    def panel(self, message: str, title: str | None = None, border_style: str | None = None) -> None:
        self._sink.emit_panel(message, title, border_style)

    def rule(self, title: str) -> None:
        self._sink.emit_rule(title)

class Form(Protocol):
    def ask(self, prompt: str, default: str | None = None, password: bool = False) -> str: ...
    def confirm(self, prompt: str, default: bool = True) -> bool: ...

class Progress(Protocol):
    def status(self, message: str) -> ContextManager[None]: ...
    # Add other progress methods if needed, aligning with existing usage or refactoring target

class Dashboard:
    def live(self) -> ContextManager[None]:
        return nullcontext()

    def add_log(self, line: str) -> None:
        _ = line
        return None

    def refresh(self) -> None:
        return None

    def mark_event(self, source: str) -> None:
        _ = source
        return None

    def set_warning(self, message: str, ttl: float = 10.0) -> None:
        _ = (message, ttl)
        return None

    def clear_warning(self) -> None:
        return None

    def set_controller_state(self, state: str) -> None:
        _ = state
        return None

class DashboardFactory(Protocol):
    def create(
        self,
        plan: list[Any],
        journal: Any,
        ui_log_file: IO[str] | None = None,
    ) -> Dashboard: ...

class UI(Protocol):
    picker: Picker
    hierarchical_picker: HierarchicalPicker
    tables: TablePresenter
    present: Presenter
    form: Form
    progress: Progress
    dashboard: DashboardFactory
