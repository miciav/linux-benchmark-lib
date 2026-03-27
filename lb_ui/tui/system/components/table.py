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
            TableModel(
                title=theme.panel_title(table.title, active=False),
                columns=table.columns,
                rows=table.rows,
            ),
            console=self._console,
            show_lines=False,
            border_style=theme.RICH_BORDER_STYLE,
            header_style=theme.DASHBOARD_HEADER_STYLE,
            title_style=theme.RICH_TITLE_SECONDARY,
            row_styles=theme.TABLE_ROW_STYLES,
        )
        self._console.print(rich_table)
