from rich.console import Console
from lb_ui.tui.system.models import TableModel
from lb_ui.tui.core.protocols import TablePresenter
from lb_ui.tui.core import theme
from lb_ui.tui.system.components.table_layout import build_rich_table


class RichTablePresenter(TablePresenter):
    def __init__(self, console: Console):
        self._console = console

    def show(self, table: TableModel) -> None:
        rich_table = build_rich_table(
            table,
            console=self._console,
            show_lines=True,
            border_style=theme.RICH_BORDER_STYLE,
            header_style=theme.RICH_ACCENT_BOLD,
            title_style=theme.RICH_ACCENT_BOLD,
        )
        self._console.print(rich_table)
