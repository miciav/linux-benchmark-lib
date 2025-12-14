from rich.console import Console
from rich.table import Table
from rich import box
from lb_ui.ui.system.models import TableModel
from lb_ui.ui.system.protocols import TablePresenter

class RichTablePresenter(TablePresenter):
    def __init__(self, console: Console):
        self._console = console

    def show(self, table: TableModel) -> None:
        rich_table = Table(
            title=table.title,
            show_lines=True,
            expand=True,
            box=box.ROUNDED,
            border_style="blue",
            header_style="bold blue",
            title_style="bold blue"
        )
        for col in table.columns:
            rich_table.add_column(col)
        for row in table.rows:
            rich_table.add_row(*row)
        self._console.print(rich_table)
