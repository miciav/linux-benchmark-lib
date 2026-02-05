"""Dashboard view showing run progress, journal, and logs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from lb_gui.widgets import JournalTable, LogViewer, PlanTable, RunStatusBar
from lb_gui.utils import set_widget_role

if TYPE_CHECKING:
    from lb_gui.viewmodels.dashboard_vm import GUIDashboardViewModel
    from lb_app.api import DashboardSnapshot


class DashboardView(QWidget):
    """View displaying run progress, journal table, and log output."""

    def __init__(
        self,
        viewmodel: "GUIDashboardViewModel",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._vm = viewmodel

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self) -> None:
        """Set up the UI layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # Title and status bar
        header_layout = QHBoxLayout()

        title = QLabel("Dashboard")
        title.setProperty("role", "title")
        header_layout.addWidget(title)

        self._run_id_label = QLabel("")
        self._run_id_label.setProperty("role", "muted")
        header_layout.addWidget(self._run_id_label)

        header_layout.addStretch()

        self._status_label = QLabel("No run active")
        set_widget_role(self._status_label, "muted")
        header_layout.addWidget(self._status_label)

        layout.addLayout(header_layout)

        # Status summary bar
        self._status_bar = RunStatusBar()
        layout.addWidget(self._status_bar)

        # Main splitter with tables and log
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Upper section: Plan and Journal tables side by side
        tables_widget = QWidget()
        tables_layout = QHBoxLayout(tables_widget)
        tables_layout.setContentsMargins(0, 0, 0, 0)

        # Plan table
        plan_group = QGroupBox("Run Plan")
        plan_layout = QVBoxLayout(plan_group)
        self._plan_table = PlanTable()
        plan_layout.addWidget(self._plan_table)
        tables_layout.addWidget(plan_group, 1)

        # Journal table
        journal_group = QGroupBox("Progress")
        journal_layout = QVBoxLayout(journal_group)
        self._journal_table = JournalTable()
        journal_layout.addWidget(self._journal_table)
        tables_layout.addWidget(journal_group, 2)

        splitter.addWidget(tables_widget)

        # Lower section: Log viewer
        log_group = QGroupBox("Log Output")
        log_layout = QVBoxLayout(log_group)
        self._log_viewer = LogViewer()
        log_layout.addWidget(self._log_viewer)
        splitter.addWidget(log_group)

        # Set initial splitter sizes (60% tables, 40% log)
        splitter.setSizes([600, 400])

        layout.addWidget(splitter, 1)

        # Warning banner (hidden by default)
        self._warning_label = QLabel("")
        self._warning_label.setObjectName("warningBanner")
        set_widget_role(self._warning_label, "status-warning")
        self._warning_label.setWordWrap(True)
        self._warning_label.hide()
        layout.addWidget(self._warning_label)

    def _connect_signals(self) -> None:
        """Connect viewmodel signals."""
        self._vm.snapshot_changed.connect(self._on_snapshot_changed)
        self._vm.log_line_received.connect(self._on_log_line)
        self._vm.status_changed.connect(self._on_status_changed)
        self._vm.warning_received.connect(self._on_warning)
        self._vm.run_finished.connect(self._on_run_finished)

    # Slots for viewmodel signals

    def _on_snapshot_changed(self, snapshot: "DashboardSnapshot") -> None:
        """Handle snapshot update."""
        # Update run ID
        self._run_id_label.setText(f"Run: {snapshot.run_id}")

        # Update plan table
        plan_rows = snapshot.plan_rows
        self._plan_table.set_rows(plan_rows)

        # Update journal table
        journal_rows = self._vm.get_journal_rows()
        self._journal_table.set_rows(journal_rows)

        # Update summary
        summary = snapshot.status_summary
        self._status_bar.set_counts(
            summary.total,
            summary.completed,
            summary.running,
            summary.failed,
            summary.pending,
        )

    def _on_log_line(self, line: str) -> None:
        """Handle incoming log line."""
        self._log_viewer.append_line(line)

    def _on_status_changed(self, status: str) -> None:
        """Handle status update."""
        self._status_label.setText(status)
        lowered = status.lower()
        if "error" in lowered or "fail" in lowered:
            set_widget_role(self._status_label, "status-error")
        elif "complet" in lowered:
            set_widget_role(self._status_label, "status-success")
        else:
            set_widget_role(self._status_label, "status-info")

    def _on_warning(self, message: str, ttl: float) -> None:
        """Handle warning message."""
        self._warning_label.setText(message)
        self._warning_label.show()
        # Auto-hide after TTL (simplified - in real implementation use QTimer)
        # For now, just show it

    def _on_run_finished(self, success: bool, error: str) -> None:
        """Handle run completion."""
        if success:
            self._status_label.setText("Run Completed")
            set_widget_role(self._status_label, "status-success")
        else:
            self._status_label.setText(f"Run Failed: {error}")
            set_widget_role(self._status_label, "status-error")

    def clear(self) -> None:
        """Clear the dashboard display."""
        self._run_id_label.setText("")
        self._status_label.setText("No run active")
        set_widget_role(self._status_label, "muted")
        self._plan_table.set_rows([])
        self._journal_table.set_rows([])
        self._log_viewer.clear()
        self._warning_label.hide()
        self._status_bar.set_counts(0, 0, 0, 0, 0)
