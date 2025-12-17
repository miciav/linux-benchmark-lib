from rich.console import Console
from lb_ui.ui.system.models import TableModel
from lb_ui.ui.system.protocols import TablePresenter
from lb_ui.ui.system.components.table_layout import build_rich_table

class RichTablePresenter(TablePresenter):
    def __init__(self, console: Console):
        self._console = console

    def show(self, table: TableModel) -> None:
        rich_table = build_rich_table(
            table,
            console=self._console,
            show_lines=True,
            border_style="blue",
            header_style="bold blue",
            title_style="bold blue",
        )
        self._console.print(rich_table)
