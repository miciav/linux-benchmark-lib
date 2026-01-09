from typing import Sequence, ContextManager, Any, IO
from dataclasses import dataclass, field
from contextlib import nullcontext

from lb_ui.tui.system.components.dashboard_adapter import DashboardAdapter
from lb_ui.tui.system.components.dashboard_base import DashboardNoOp
from lb_ui.tui.system.components.presenter_base import PresenterBase, PresenterSink
from lb_ui.tui.system.protocols import UI, Picker, TablePresenter, Form, Progress, Dashboard, DashboardFactory, HierarchicalPicker
from lb_ui.tui.system.models import TableModel, PickItem, SelectionNode

@dataclass
class RecordedTable:
    model: TableModel

@dataclass
class HeadlessUI(UI):
    recorded_tables: list[RecordedTable] = field(default_factory=list)
    recorded_messages: list[str] = field(default_factory=list)
    recorded_dashboard_logs: list[str] = field(default_factory=list)
    
    # Configuration for automated responses
    next_pick_one: PickItem | None = None
    next_pick_many: list[PickItem] | None = field(default_factory=list)
    next_hierarchical_pick: SelectionNode | None = None
    next_hierarchical_pick_path: list[str] = field(default_factory=list)
    next_form_response: str = "default"
    next_confirm_response: bool = True

    def __post_init__(self):
        self.picker = _HeadlessPicker(self)
        self.hierarchical_picker = _HeadlessHierarchicalPicker(self)
        self.tables = _HeadlessTablePresenter(self)
        self.present = _HeadlessPresenter(self)
        self.form = _HeadlessForm(self)
        self.progress = _HeadlessProgress(self)
        self.dashboard = _HeadlessDashboardFactory(self)

class _HeadlessPicker(Picker):
    def __init__(self, ui: HeadlessUI):
        self._ui = ui

    def pick_one(self, items: Sequence[PickItem], *, title: str, query_hint: str = "") -> PickItem | None:
        return self._ui.next_pick_one

    def pick_many(self, items: Sequence[PickItem], *, title: str, query_hint: str = "") -> list[PickItem] | None:
        return self._ui.next_pick_many

class _HeadlessHierarchicalPicker(HierarchicalPicker):
    def __init__(self, ui: HeadlessUI):
        self._ui = ui

    def pick_one(self, root: SelectionNode, *, title: str) -> SelectionNode | None:
        if self._ui.next_hierarchical_pick is not None:
            return self._ui.next_hierarchical_pick
        if self._ui.next_hierarchical_pick_path:
            return self._pick_by_path(root, self._ui.next_hierarchical_pick_path)
        return self._first_leaf(root)

    @classmethod
    def _pick_by_path(cls, root: SelectionNode, path: Sequence[str]) -> SelectionNode | None:
        node: SelectionNode | None = root
        segments = list(path)
        if segments and segments[0] == root.id:
            segments = segments[1:]

        for segment in segments:
            if node is None:
                return None
            node = cls._find_child(node, segment)

        if node is None:
            return None
        return cls._first_leaf(node)

    @staticmethod
    def _find_child(parent: SelectionNode, segment: str) -> SelectionNode | None:
        for child in parent.children:
            if child.id == segment:
                return child
        for child in parent.children:
            if child.label == segment:
                return child
        return None

    @classmethod
    def _first_leaf(cls, node: SelectionNode) -> SelectionNode | None:
        if not node.children:
            return node
        for child in node.children:
            leaf = cls._first_leaf(child)
            if leaf is not None:
                return leaf
        return None

class _HeadlessTablePresenter(TablePresenter):
    def __init__(self, ui: HeadlessUI):
        self._ui = ui

    def show(self, table: TableModel) -> None:
        self._ui.recorded_tables.append(RecordedTable(table))

class _HeadlessPresenterSink(PresenterSink):
    def __init__(self, ui: HeadlessUI) -> None:
        self._ui = ui

    def emit(self, level: str, message: str) -> None:
        self._ui.recorded_messages.append(f"{level.upper()}: {message}")

    def emit_panel(
        self,
        message: str,
        title: str | None,
        border_style: str | None,
    ) -> None:
        self._ui.recorded_messages.append(f"PANEL: {title} - {message}")

    def emit_rule(self, title: str) -> None:
        self._ui.recorded_messages.append(f"RULE: {title}")

class _HeadlessPresenter(PresenterBase):
    def __init__(self, ui: HeadlessUI) -> None:
        super().__init__(_HeadlessPresenterSink(ui))

class _HeadlessForm(Form):
    def __init__(self, ui: HeadlessUI):
        self._ui = ui

    def ask(self, prompt: str, default: str | None = None, password: bool = False) -> str:
        return self._ui.next_form_response

    def confirm(self, prompt: str, default: bool = True) -> bool:
        return self._ui.next_confirm_response

class _HeadlessProgress(Progress):
    def __init__(self, ui: HeadlessUI):
        self._ui = ui
        
    def status(self, message: str) -> ContextManager[None]:
        self._ui.recorded_messages.append(f"STATUS: {message}")
        return nullcontext()

class _HeadlessDashboardSink(DashboardNoOp):
    def __init__(self, ui: HeadlessUI) -> None:
        self._ui = ui

    def live(self) -> ContextManager[None]:
        self._ui.recorded_messages.append("DASHBOARD: live()")
        return nullcontext()

    def add_log(self, line: str) -> None:
        self._ui.recorded_dashboard_logs.append(line)

class _HeadlessDashboardFactory(DashboardFactory):
    def __init__(self, ui: HeadlessUI):
        self._ui = ui

    def create(
        self,
        plan: list[Any],
        journal: Any,
        ui_log_file: IO[str] | None = None,
    ) -> Dashboard:
        self._ui.recorded_messages.append(f"DASHBOARD: create(plan={len(plan)} items)")
        return DashboardAdapter(_HeadlessDashboardSink(self._ui))
