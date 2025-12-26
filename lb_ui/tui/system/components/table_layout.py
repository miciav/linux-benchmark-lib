from __future__ import annotations

import shutil

from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

from lb_ui.tui.system.models import TableModel


def _console_width(console: Console) -> int | None:
    try:
        width = int(getattr(console.size, "width"))
        if width > 0:
            return width
    except Exception:
        pass
    try:
        width = int(shutil.get_terminal_size(fallback=(100, 24)).columns)
        return width if width > 0 else None
    except Exception:
        return None


def build_rich_table(
    model: TableModel,
    *,
    console: Console,
    show_lines: bool = True,
    border_style: str = "blue",
    header_style: str = "bold blue",
    title_style: str = "bold blue",
    box_style: box.Box = box.ROUNDED,
) -> Table:
    """
    Build a Rich Table from a TableModel that fits the current terminal width.

    Columns are rendered as single-line and truncated with ellipsis when needed.
    """
    term_width = _console_width(console)
    max_table_width = max(60, (term_width - 2) if term_width else 100)
    min_col_width = 4

    title_text = Text.from_markup(str(model.title))
    title_text.no_wrap = True
    title_text.overflow = "ellipsis"
    # Avoid the title forcing the table to expand beyond the terminal width.
    # Rich accounts for borders/padding; leave a small margin.
    title_max = max(10, max_table_width - 6)
    if len(title_text) > title_max:
        title_text.truncate(title_max, overflow="ellipsis")

    rich_table = Table(
        title=title_text,
        show_lines=show_lines,
        expand=True,
        width=max_table_width,
        box=box_style,
        border_style=border_style,
        header_style=header_style,
        title_style=title_style,
    )

    def _cell_width(value: str) -> int:
        # Use the longest line width for multi-line cells.
        return max((len(line) for line in str(value).splitlines()), default=0)

    column_count = max(1, len(model.columns))
    # Rough overhead for borders + separators + padding.
    overhead = 4 + (column_count - 1) * 3

    desired: list[int] = []
    for idx, col in enumerate(model.columns):
        max_len = _cell_width(col)
        for row in model.rows:
            if idx < len(row):
                max_len = max(max_len, _cell_width(row[idx]))
        desired.append(max(min_col_width, min(max_len, max_table_width)))

    # Shrink widest columns until the approximate total fits.
    while sum(desired) + overhead > max_table_width:
        widest = max(range(len(desired)), key=lambda i: desired[i])
        if desired[widest] <= min_col_width:
            break
        desired[widest] -= 1

    for idx, col in enumerate(model.columns):
        rich_table.add_column(
            col,
            overflow="ellipsis",
            no_wrap=True,
            min_width=min_col_width,
            max_width=desired[idx] if idx < len(desired) else None,
        )
    for row in model.rows:
        rich_table.add_row(*row)
    return rich_table
