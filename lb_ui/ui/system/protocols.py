from typing import Any, Protocol, Sequence, ContextManager, IO
from lb_ui.ui.system.models import TableModel, PickItem, SelectionNode

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
    ) -> list[PickItem]: ...

class HierarchicalPicker(Protocol):
    def pick_one(
        self,
        root: SelectionNode,
        *,
        title: str
    ) -> SelectionNode | None: ...

class Presenter(Protocol):
    def info(self, message: str) -> None: ...
    def warning(self, message: str) -> None: ...
    def error(self, message: str) -> None: ...
    def success(self, message: str) -> None: ...
    def panel(self, message: str, title: str | None = None, border_style: str | None = None) -> None: ...
    def rule(self, title: str) -> None: ...

class Form(Protocol):
    def ask(self, prompt: str, default: str | None = None, password: bool = False) -> str: ...
    def confirm(self, prompt: str, default: bool = True) -> bool: ...

class Progress(Protocol):
    def status(self, message: str) -> ContextManager[None]: ...
    # Add other progress methods if needed, aligning with existing usage or refactoring target

class Dashboard(Protocol):
    def live(self) -> ContextManager[None]: ...
    def add_log(self, line: str) -> None: ...
    def refresh(self) -> None: ...
    def mark_event(self, source: str) -> None: ...
    def set_warning(self, message: str, ttl: float = 10.0) -> None: ...
    def clear_warning(self) -> None: ...
    def set_controller_state(self, state: str) -> None: ...

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
