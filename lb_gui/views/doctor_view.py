"""Doctor view for running environment health checks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from lb_gui.utils import set_widget_role

if TYPE_CHECKING:
    from lb_gui.viewmodels.doctor_vm import DoctorViewModel


class DoctorView(QWidget):
    """View for running environment health checks."""

    CHECK_HEADERS = ["Group", "Check", "Status", "Required"]

    def __init__(
        self,
        viewmodel: "DoctorViewModel",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._vm = viewmodel

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self) -> None:
        """Set up the UI layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Title
        title = QLabel("Doctor")
        title.setProperty("role", "title")
        layout.addWidget(title)

        # Description
        desc = QLabel("Check your environment for benchmark compatibility.")
        desc.setProperty("role", "muted")
        layout.addWidget(desc)

        # Run button and progress
        btn_layout = QHBoxLayout()

        self._run_btn = QPushButton("Run All Checks")
        self._run_btn.clicked.connect(self._on_run_checks)
        btn_layout.addWidget(self._run_btn)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)  # Indeterminate
        self._progress.setVisible(False)
        btn_layout.addWidget(self._progress)

        self._progress_label = QLabel("")
        self._progress_label.setProperty("role", "muted")
        btn_layout.addWidget(self._progress_label)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # Summary
        summary_layout = QHBoxLayout()
        self._total_label = QLabel("Total: -")
        self._passed_label = QLabel("Passed: -")
        set_widget_role(self._passed_label, "status-success")
        self._failed_label = QLabel("Failed: -")
        set_widget_role(self._failed_label, "status-error")
        summary_layout.addWidget(self._total_label)
        summary_layout.addWidget(self._passed_label)
        summary_layout.addWidget(self._failed_label)
        summary_layout.addStretch()
        layout.addLayout(summary_layout)

        # Results table
        results_group = QGroupBox("Check Results")
        results_layout = QVBoxLayout(results_group)
        self._table = QTableWidget()
        self._table.setColumnCount(len(self.CHECK_HEADERS))
        self._table.setHorizontalHeaderLabels(self.CHECK_HEADERS)
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        results_layout.addWidget(self._table)
        layout.addWidget(results_group, 1)

        # Info messages
        info_group = QGroupBox("Information")
        info_layout = QVBoxLayout(info_group)
        self._info_text = QPlainTextEdit()
        self._info_text.setReadOnly(True)
        self._info_text.setMaximumHeight(100)
        info_layout.addWidget(self._info_text)
        layout.addWidget(info_group)

        # Status
        self._status_label = QLabel("Run checks to see results")
        self._status_label.setProperty("role", "muted")
        layout.addWidget(self._status_label)

    def _connect_signals(self) -> None:
        """Connect viewmodel signals."""
        self._vm.checks_started.connect(self._on_checks_started)
        self._vm.checks_completed.connect(self._on_checks_completed)
        self._vm.check_progress.connect(self._on_check_progress)
        self._vm.error_occurred.connect(self._on_error)

    def _on_run_checks(self) -> None:
        """Handle run checks button click."""
        # Try to load config for connectivity checks
        self._vm.load_config()
        self._vm.run_all_checks()

    def _on_checks_started(self) -> None:
        """Handle checks started."""
        self._run_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._table.setRowCount(0)
        self._info_text.clear()
        self._status_label.setText("Running checks...")
        set_widget_role(self._status_label, "status-info")

    def _on_check_progress(self, message: str) -> None:
        """Handle check progress update."""
        self._progress_label.setText(message)

    def _on_checks_completed(self, reports: list) -> None:
        """Handle checks completed."""
        self._run_btn.setEnabled(True)
        self._progress.setVisible(False)
        self._progress_label.setText("")

        # Update summary
        summary = self._vm.get_summary()
        self._total_label.setText(f"Total: {summary['total']}")
        self._passed_label.setText(f"Passed: {summary['passed']}")
        self._failed_label.setText(f"Failed: {summary['failed']}")

        # Update results table
        results = self._vm.get_flattened_results()
        self._table.setRowCount(len(results))
        for i, result in enumerate(results):
            for j, header in enumerate(self.CHECK_HEADERS):
                value = result.get(header, "")
                item = QTableWidgetItem(value)

                # Color-code status
                if header == "Status":
                    if value == "Pass":
                        item.setForeground(Qt.GlobalColor.darkGreen)
                    else:
                        item.setForeground(Qt.GlobalColor.red)
                        item.setBackground(Qt.GlobalColor.yellow)

                self._table.setItem(i, j, item)

        # Update info messages
        messages = self._vm.get_info_messages()
        if messages:
            self._info_text.setPlainText("\n".join(messages))
        else:
            self._info_text.setPlainText("(No additional information)")

        # Update status
        if self._vm.all_passed:
            self._status_label.setText("All checks passed!")
            set_widget_role(self._status_label, "status-success")
        else:
            failures = self._vm.total_failures
            self._status_label.setText(f"{failures} check(s) failed")
            set_widget_role(self._status_label, "status-error")

    def _on_error(self, message: str) -> None:
        """Handle error from viewmodel."""
        self._run_btn.setEnabled(True)
        self._progress.setVisible(False)
        self._progress_label.setText("")
        self._status_label.setText(message)
        set_widget_role(self._status_label, "status-error")
