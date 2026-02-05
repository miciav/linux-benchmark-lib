"""Qt helper utilities."""

from __future__ import annotations

from PySide6.QtWidgets import QLayout, QTableWidget, QWidget


def set_table_headers(table: QTableWidget, headers: list[str]) -> None:
    """Set column count and header labels for a table."""
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)


def clear_layout(layout: QLayout) -> None:
    """Remove all items from a layout."""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)


def set_widget_role(widget: QWidget, role: str | None) -> None:
    """Set a role dynamic property and refresh style."""
    widget.setProperty("role", role)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
