"""Status summary bar for run progress."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from lb_gui.utils import set_widget_role


class RunStatusBar(QWidget):
    """Widget showing run progress summary counts."""

    def __init__(self, parent: object | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        self._total = self._make_label("Total", "0", "muted")
        self._completed = self._make_label("Completed", "0", "status-success")
        self._running = self._make_label("Running", "0", "status-info")
        self._failed = self._make_label("Failed", "0", "status-error")
        self._pending = self._make_label("Pending", "0", "muted")

        layout.addWidget(self._total)
        layout.addWidget(self._completed)
        layout.addWidget(self._running)
        layout.addWidget(self._failed)
        layout.addWidget(self._pending)
        layout.addStretch()

    def set_counts(
        self,
        total: int,
        completed: int,
        running: int,
        failed: int,
        pending: int,
    ) -> None:
        """Update summary counters."""
        self._set_label(self._total, "Total", total)
        self._set_label(self._completed, "Completed", completed)
        self._set_label(self._running, "Running", running)
        self._set_label(self._failed, "Failed", failed)
        self._set_label(self._pending, "Pending", pending)

    def _make_label(self, name: str, value: str, role: str) -> QLabel:
        label = QLabel(f"{name}: {value}")
        set_widget_role(label, role)
        return label

    def _set_label(self, label: QLabel, name: str, value: int) -> None:
        label.setText(f"{name}: {value}")
