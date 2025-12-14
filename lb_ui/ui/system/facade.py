from typing import Sequence

from rich.console import Console

from lb_ui.ui.system.protocols import (
    UI,
    Picker,
    TablePresenter,
    Presenter,
    Form,
    Progress,
    DashboardFactory,
    HierarchicalPicker,
)
from lb_ui.ui.system.components.table import RichTablePresenter
from lb_ui.ui.system.components.picker import PowerPicker
from lb_ui.ui.system.components.hierarchical_picker import PowerHierarchicalPicker
from lb_ui.ui.system.components.presenter import RichPresenter
from lb_ui.ui.system.components.form import RichForm
from lb_ui.ui.system.components.progress import RichProgress
from lb_ui.ui.system.components.dashboard import RichDashboardFactory
from lb_ui.ui.system.models import TableModel

class TUI(UI):
    def __init__(self, console: Console | None = None):
        self._console = console or Console()
        self.picker: Picker = PowerPicker()
        self.hierarchical_picker: HierarchicalPicker = PowerHierarchicalPicker()
        self.tables: TablePresenter = RichTablePresenter(self._console)
        self.present: Presenter = RichPresenter(self._console)
        self.form: Form = RichForm(self._console)
        self.progress: Progress = RichProgress(self._console)
        self.dashboard: DashboardFactory = RichDashboardFactory(self._console)

    def show_table(self, title: str, columns: Sequence[str], rows: list[Sequence[str]]) -> None:
        """Render a table using the facade for compatibility with legacy callers."""
        model = TableModel(title=title, columns=list(columns), rows=[list(r) for r in rows])
        self.tables.show(model)
