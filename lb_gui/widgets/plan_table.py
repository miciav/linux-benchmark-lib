"""Plan table widget for dashboard."""

from __future__ import annotations

from typing import Sequence

from PySide6.QtWidgets import QTableWidget, QTableWidgetItem


class PlanTable(QTableWidget):
    """Table for displaying the run plan."""

    HEADERS = ["Workload", "Config"]

    def __init__(self, parent: object | None = None) -> None:
        super().__init__(parent)
        self.setColumnCount(len(self.HEADERS))
        self.setHorizontalHeaderLabels(self.HEADERS)
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
                self.setItem(i, j, item)
