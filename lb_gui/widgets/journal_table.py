"""Journal table widget for dashboard."""

from __future__ import annotations

from typing import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem


class JournalTable(QTableWidget):
    """Table for displaying run journal progress."""

    HEADERS = [
        "Host",
        "Workload",
        "Intensity",
        "Status",
        "Progress",
        "Current Action",
        "Last Rep Time",
    ]

    STATUS_COLUMN = 3

    def __init__(self, parent: object | None = None) -> None:
        super().__init__(parent)
        self.setColumnCount(len(self.HEADERS))
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.horizontalHeader().setStretchLastSection(True)
        self.verticalHeader().setVisible(False)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

    def set_rows(self, rows: Sequence[Sequence[object]]) -> None:
        """Replace the table contents with the provided rows."""
        self.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, cell in enumerate(row):
                item = QTableWidgetItem(str(cell))
                if j == self.STATUS_COLUMN:
                    self._apply_status_style(item, str(cell))
                self.setItem(i, j, item)

    def _apply_status_style(self, item: QTableWidgetItem, status: str) -> None:
        """Apply foreground colors based on status text."""
        value = status.strip().lower()
        if value == "completed":
            item.setForeground(Qt.GlobalColor.darkGreen)
        elif value == "running":
            item.setForeground(Qt.GlobalColor.blue)
        elif value == "failed":
            item.setForeground(Qt.GlobalColor.red)
