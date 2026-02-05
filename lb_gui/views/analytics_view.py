"""Analytics view for running analytics on benchmark results."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from lb_gui.utils import set_widget_role

if TYPE_CHECKING:
    from lb_gui.viewmodels.analytics_vm import AnalyticsViewModel
    from lb_common.api import RunInfo


class AnalyticsView(QWidget):
    """View for running analytics on benchmark results."""

    RUN_HEADERS = ["Run ID", "Created", "Workloads"]

    def __init__(
        self,
        viewmodel: "AnalyticsViewModel",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._vm = viewmodel

        self._setup_ui()
        self._connect_signals()
        self._initial_load()

    def _initial_load(self) -> None:
        """Load runs on first render."""
        self._vm.refresh_runs()

    def _setup_ui(self) -> None:
        """Set up the UI layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Title
        title = QLabel("Analytics")
        title.setProperty("role", "title")
        layout.addWidget(title)

        # Main splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: Run selection
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # Refresh button
        refresh_btn = QPushButton("Refresh Runs")
        refresh_btn.clicked.connect(self._on_refresh)
        left_layout.addWidget(refresh_btn)

        # Run table
        run_group = QGroupBox("Select Run")
        run_layout = QVBoxLayout(run_group)
        self._run_table = QTableWidget()
        self._run_table.setColumnCount(len(self.RUN_HEADERS))
        self._run_table.setHorizontalHeaderLabels(self.RUN_HEADERS)
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
        self._run_table.itemSelectionChanged.connect(self._on_run_selection_changed)
        run_layout.addWidget(self._run_table)
        left_layout.addWidget(run_group, 1)

        splitter.addWidget(left_widget)

        # Right: Options and execution
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # Options group
        options_group = QGroupBox("Options")
        options_layout = QFormLayout(options_group)

        # Analytics kind
        self._kind_combo = QComboBox()
        for kind in self._vm.available_kinds:
            self._kind_combo.addItem(str(kind), kind)
        self._kind_combo.currentIndexChanged.connect(self._on_kind_changed)
        options_layout.addRow("Type:", self._kind_combo)

        right_layout.addWidget(options_group)

        # Filters group
        filters_group = QGroupBox("Filters (optional)")
        filters_layout = QHBoxLayout(filters_group)

        # Workloads filter
        workloads_layout = QVBoxLayout()
        workloads_layout.addWidget(QLabel("Workloads:"))
        self._workloads_list = QListWidget()
        self._workloads_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self._workloads_list.itemSelectionChanged.connect(
            self._on_workloads_selection_changed
        )
        workloads_layout.addWidget(self._workloads_list)
        filters_layout.addLayout(workloads_layout)

        # Hosts filter
        hosts_layout = QVBoxLayout()
        hosts_layout.addWidget(QLabel("Hosts:"))
        self._hosts_list = QListWidget()
        self._hosts_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self._hosts_list.itemSelectionChanged.connect(self._on_hosts_selection_changed)
        hosts_layout.addWidget(self._hosts_list)
        filters_layout.addLayout(hosts_layout)

        right_layout.addWidget(filters_group, 1)

        # Run button and progress
        action_layout = QHBoxLayout()

        self._run_btn = QPushButton("Run Analytics")
        self._run_btn.setEnabled(False)
        self._run_btn.clicked.connect(self._on_run_analytics)
        action_layout.addWidget(self._run_btn)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setRange(0, 0)  # Indeterminate
        action_layout.addWidget(self._progress)

        action_layout.addStretch()
        right_layout.addLayout(action_layout)

        # Results group
        results_group = QGroupBox("Generated Artifacts")
        results_layout = QVBoxLayout(results_group)
        self._artifacts_list = QListWidget()
        self._artifacts_list.itemDoubleClicked.connect(self._on_artifact_double_clicked)
        results_layout.addWidget(self._artifacts_list)
        right_layout.addWidget(results_group)

        splitter.addWidget(right_widget)

        # Set splitter sizes
        splitter.setSizes([400, 600])

        layout.addWidget(splitter, 1)

        # Status label
        self._status_label = QLabel("")
        self._status_label.setProperty("role", "muted")
        layout.addWidget(self._status_label)

    def _connect_signals(self) -> None:
        """Connect viewmodel signals."""
        self._vm.runs_changed.connect(self._on_runs_changed)
        self._vm.run_selected.connect(self._on_vm_run_selected)
        self._vm.analytics_started.connect(self._on_analytics_started)
        self._vm.analytics_completed.connect(self._on_analytics_completed)
        self._vm.analytics_failed.connect(self._on_analytics_failed)
        self._vm.error_occurred.connect(self._on_error)

    def _on_refresh(self) -> None:
        """Handle refresh button click."""
        self._vm.refresh_runs()

    def _on_run_selection_changed(self) -> None:
        """Handle run table selection change."""
        selected = self._run_table.selectedItems()
        if selected:
            row = selected[0].row()
            run_id = self._run_table.item(row, 0).text()
            self._vm.select_run(run_id)
        else:
            self._vm.select_run(None)

    def _on_kind_changed(self, index: int) -> None:
        """Handle analytics kind change."""
        kind = self._kind_combo.itemData(index)
        if kind:
            self._vm.selected_kind = kind

    def _on_workloads_selection_changed(self) -> None:
        """Handle workloads filter selection change."""
        selected = [item.text() for item in self._workloads_list.selectedItems()]
        self._vm.selected_workloads = selected

    def _on_hosts_selection_changed(self) -> None:
        """Handle hosts filter selection change."""
        selected = [item.text() for item in self._hosts_list.selectedItems()]
        self._vm.selected_hosts = selected

    def _on_run_analytics(self) -> None:
        """Handle run analytics button click."""
        self._vm.run_analytics()

    def _on_runs_changed(self, runs: list) -> None:
        """Handle runs list update."""
        rows = self._vm.get_run_table_rows()
        self._run_table.setRowCount(len(rows))

        for i, row in enumerate(rows):
            for j, cell in enumerate(row):
                item = QTableWidgetItem(str(cell))
                self._run_table.setItem(i, j, item)

        self._status_label.setText(f"{len(runs)} run(s) available")
        set_widget_role(self._status_label, "muted")

    def _on_vm_run_selected(self, run: "RunInfo | None") -> None:
        """Handle run selection in viewmodel."""
        # Update filter lists
        self._workloads_list.clear()
        self._hosts_list.clear()

        if run is not None:
            for workload in self._vm.available_workloads:
                item = QListWidgetItem(workload)
                item.setSelected(True)
                self._workloads_list.addItem(item)

            for host in self._vm.available_hosts:
                item = QListWidgetItem(host)
                item.setSelected(True)
                self._hosts_list.addItem(item)

        # Update run button state
        can_run, _ = self._vm.can_run_analytics()
        self._run_btn.setEnabled(can_run)

    def _on_analytics_started(self) -> None:
        """Handle analytics started."""
        self._run_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._status_label.setText("Running analytics...")
        set_widget_role(self._status_label, "status-info")
        self._artifacts_list.clear()

    def _on_analytics_completed(self, artifacts: list) -> None:
        """Handle analytics completed."""
        self._run_btn.setEnabled(True)
        self._progress.setVisible(False)

        self._artifacts_list.clear()
        for path in artifacts:
            self._artifacts_list.addItem(str(path))

        self._status_label.setText(f"Analytics completed: {len(artifacts)} artifact(s)")
        set_widget_role(self._status_label, "status-success")

    def _on_analytics_failed(self, error: str) -> None:
        """Handle analytics failure."""
        self._run_btn.setEnabled(True)
        self._progress.setVisible(False)
        self._status_label.setText(f"Analytics failed: {error}")
        set_widget_role(self._status_label, "status-error")

    def _on_error(self, message: str) -> None:
        """Handle error from viewmodel."""
        self._status_label.setText(message)
        set_widget_role(self._status_label, "status-error")

    def _on_artifact_double_clicked(self, item: QListWidgetItem) -> None:
        """Handle artifact double-click to open."""
        path = Path(item.text())
        if path.exists():
            self._open_path(path)
        else:
            QMessageBox.warning(
                self,
                "File Not Found",
                f"The file does not exist:\n{path}",
            )

    def _open_path(self, path: Path) -> None:
        """Open a path in the system file browser or application."""
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", str(path)])
            elif sys.platform == "win32":
                subprocess.run(["start", "", str(path)], shell=True)
            else:
                subprocess.run(["xdg-open", str(path)])
        except Exception as e:
            QMessageBox.warning(
                self,
                "Error",
                f"Could not open file:\n{e}",
            )
