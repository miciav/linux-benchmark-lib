"""Results view for browsing past benchmark runs."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from lb_gui.utils import set_widget_role

if TYPE_CHECKING:
    from lb_gui.viewmodels.results_vm import ResultsViewModel
    from lb_common.api import RunInfo


class ResultsView(QWidget):
    """View for browsing and inspecting past benchmark runs."""

    def __init__(
        self,
        viewmodel: "ResultsViewModel",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._vm = viewmodel

        self._setup_ui()
        self._connect_signals()
        self._initial_load()

    def _initial_load(self) -> None:
        """Load runs on first render."""
        if not self._vm.is_configured:
            if not self._vm.configure():
                return
        self._vm.refresh_runs()

    def _setup_ui(self) -> None:
        """Set up the UI layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Title
        title = QLabel("Results")
        title.setProperty("role", "title")
        layout.addWidget(title)

        # Refresh button
        btn_layout = QHBoxLayout()
        refresh_btn = QPushButton("Refresh Runs")
        refresh_btn.clicked.connect(self._on_refresh)
        btn_layout.addWidget(refresh_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # Splitter for table and details
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: Run table
        self._run_table = QTableWidget()
        self._run_table.setColumnCount(len(self._vm.RUN_HEADERS))
        self._run_table.setHorizontalHeaderLabels(self._vm.RUN_HEADERS)
        self._run_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._run_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._run_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self._run_table.horizontalHeader().setStretchLastSection(True)
        self._run_table.verticalHeader().setVisible(False)
        self._run_table.setAlternatingRowColors(True)
        self._run_table.setShowGrid(False)
        self._run_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._run_table.itemSelectionChanged.connect(self._on_selection_changed)
        splitter.addWidget(self._run_table)

        # Right: Details panel
        details_widget = QWidget()
        details_layout = QVBoxLayout(details_widget)
        details_layout.setContentsMargins(0, 0, 0, 0)

        details_group = QGroupBox("Run Details")
        self._details_form = QFormLayout(details_group)
        self._detail_labels: dict[str, QLabel] = {}

        # Create detail labels
        detail_fields = [
            "Run ID",
            "Created",
            "Hosts",
            "Workloads",
            "Output Directory",
            "Report Directory",
            "Export Directory",
            "Journal Path",
        ]
        for field in detail_fields:
            label = QLabel("-")
            label.setWordWrap(True)
            label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            self._detail_labels[field] = label
            self._details_form.addRow(f"{field}:", label)

        details_layout.addWidget(details_group)

        # Action buttons
        action_layout = QHBoxLayout()

        self._open_output_btn = QPushButton("Open Output Dir")
        self._open_output_btn.setEnabled(False)
        self._open_output_btn.clicked.connect(self._on_open_output)
        action_layout.addWidget(self._open_output_btn)

        self._open_report_btn = QPushButton("Open Report Dir")
        self._open_report_btn.setEnabled(False)
        self._open_report_btn.clicked.connect(self._on_open_report)
        action_layout.addWidget(self._open_report_btn)

        action_layout.addStretch()
        details_layout.addLayout(action_layout)

        details_layout.addStretch()
        splitter.addWidget(details_widget)

        # Set splitter sizes (60% table, 40% details)
        splitter.setSizes([600, 400])

        layout.addWidget(splitter, 1)

        # Status label
        self._status_label = QLabel("")
        self._status_label.setProperty("role", "muted")
        layout.addWidget(self._status_label)

    def _connect_signals(self) -> None:
        """Connect viewmodel signals."""
        self._vm.runs_changed.connect(self._on_runs_changed)
        self._vm.selection_changed.connect(self._on_vm_selection_changed)
        self._vm.error_occurred.connect(self._on_error)

    def _on_refresh(self) -> None:
        """Handle refresh button click."""
        if not self._vm.is_configured:
            # Try to configure with default
            if not self._vm.configure():
                return
        self._vm.refresh_runs()

    def _on_selection_changed(self) -> None:
        """Handle table selection change."""
        selected = self._run_table.selectedItems()
        if selected:
            row = selected[0].row()
            run_id = self._run_table.item(row, 0).text()
            self._vm.select_run(run_id)
        else:
            self._vm.select_run(None)

    def _on_runs_changed(self, runs: list) -> None:
        """Handle runs list update."""
        rows = self._vm.get_run_table_rows()
        self._run_table.setRowCount(len(rows))

        for i, row in enumerate(rows):
            for j, cell in enumerate(row):
                item = QTableWidgetItem(str(cell))
                self._run_table.setItem(i, j, item)

        self._status_label.setText(f"{len(runs)} run(s) found")
        set_widget_role(self._status_label, "muted")

    def _on_vm_selection_changed(self, run: "RunInfo | None") -> None:
        """Handle viewmodel selection change."""
        if run is None:
            for label in self._detail_labels.values():
                label.setText("-")
            self._open_output_btn.setEnabled(False)
            self._open_report_btn.setEnabled(False)
            return

        details = self._vm.get_run_details(run)
        for field, label in self._detail_labels.items():
            label.setText(details.get(field, "-"))

        self._open_output_btn.setEnabled(run.output_root is not None)
        self._open_report_btn.setEnabled(run.report_root is not None)

    def _on_error(self, message: str) -> None:
        """Handle error from viewmodel."""
        self._status_label.setText(message)
        set_widget_role(self._status_label, "status-error")

    def _on_open_output(self) -> None:
        """Open the output directory in file browser."""
        path = self._vm.open_output_directory()
        if path:
            self._open_path(path)

    def _on_open_report(self) -> None:
        """Open the report directory in file browser."""
        path = self._vm.open_report_directory()
        if path:
            self._open_path(path)

    def _open_path(self, path: Path) -> None:
        """Open a path in the system file browser."""
        if not path.exists():
            QMessageBox.warning(
                self,
                "Path Not Found",
                f"The path does not exist:\n{path}",
            )
            return

        try:
            if sys.platform == "darwin":
                subprocess.run(["open", str(path)])
            elif sys.platform == "win32":
                subprocess.run(["explorer", str(path)])
            else:
                subprocess.run(["xdg-open", str(path)])
        except Exception as e:
            QMessageBox.warning(
                self,
                "Error",
                f"Could not open path:\n{e}",
            )
