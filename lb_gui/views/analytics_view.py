"""Analytics view: unify an experiment's datasets into Parquet tables."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
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

from lb_gui.utils import format_datetime, set_widget_role

if TYPE_CHECKING:
    from lb_app.api import ExperimentInfo, UnificationPreview
    from lb_gui.viewmodels.analytics_vm import AnalyticsViewModel


class AnalyticsView(QWidget):
    """Pick an experiment, prepare its unification, write it."""

    EXPERIMENT_HEADERS: ClassVar[list[str]] = [
        "Experiment",
        "Runs",
        "Hosts",
        "Workloads",
        "Last run",
    ]

    def __init__(
        self, viewmodel: AnalyticsViewModel, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._vm = viewmodel
        self._setup_ui()
        self._connect_signals()
        self._vm.refresh_runs()
        self._on_experiments_changed(self._vm.experiments)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        title = QLabel("Analytics")
        title.setProperty("role", "title")
        layout.addWidget(title)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._vm.refresh_runs)
        left_layout.addWidget(refresh_btn)
        group = QGroupBox("Experiments")
        group_layout = QVBoxLayout(group)
        self._experiment_table = QTableWidget(0, len(self.EXPERIMENT_HEADERS))
        self._experiment_table.setHorizontalHeaderLabels(self.EXPERIMENT_HEADERS)
        self._experiment_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._experiment_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self._experiment_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._experiment_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._experiment_table.itemSelectionChanged.connect(self._on_row_changed)
        group_layout.addWidget(self._experiment_table)
        left_layout.addWidget(group, 1)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        runs_group = QGroupBox("Runs in the selection")
        runs_layout = QVBoxLayout(runs_group)
        self._runs_list = QListWidget()
        runs_layout.addWidget(self._runs_list)
        right_layout.addWidget(runs_group)

        filters = QGroupBox("Filters")
        filters_layout = QHBoxLayout(filters)
        self._hosts_list = self._filter_list(filters_layout, "Hosts:")
        self._workloads_list = self._filter_list(filters_layout, "Workloads:")
        self._hosts_list.itemSelectionChanged.connect(self._on_hosts_changed)
        self._workloads_list.itemSelectionChanged.connect(self._on_workloads_changed)
        right_layout.addWidget(filters)

        actions = QHBoxLayout()
        self._prepare_btn = QPushButton("Prepare")
        self._prepare_btn.clicked.connect(self._vm.prepare)
        self._unify_btn = QPushButton("Unify")
        self._unify_btn.clicked.connect(self._vm.unify)
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        for widget in (self._prepare_btn, self._unify_btn, self._progress):
            actions.addWidget(widget)
        right_layout.addLayout(actions)

        summary = QGroupBox("Summary")
        summary_layout = QVBoxLayout(summary)
        self._summary_table = QTableWidget(0, 2)
        self._summary_table.setHorizontalHeaderLabels(["Field", "Value"])
        self._summary_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._summary_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        summary_layout.addWidget(self._summary_table)
        right_layout.addWidget(summary, 1)

        result = QGroupBox("Result")
        result_layout = QVBoxLayout(result)
        self._artifacts_list = QListWidget()
        self._artifacts_list.itemDoubleClicked.connect(self._on_artifact_double_clicked)
        result_layout.addWidget(self._artifacts_list)
        command_row = QHBoxLayout()
        self._command_edit = QLineEdit()
        self._command_edit.setReadOnly(True)
        copy_btn = QPushButton("Copy")
        copy_btn.clicked.connect(
            lambda: QApplication.clipboard().setText(self._command_edit.text())
        )
        command_row.addWidget(self._command_edit)
        command_row.addWidget(copy_btn)
        result_layout.addLayout(command_row)
        right_layout.addWidget(result)

        splitter.addWidget(right)
        layout.addWidget(splitter, 1)
        self._status_label = QLabel("")
        layout.addWidget(self._status_label)
        self._sync_buttons()

    @staticmethod
    def _filter_list(parent: QHBoxLayout, label: str) -> QListWidget:
        column = QVBoxLayout()
        column.addWidget(QLabel(label))
        widget = QListWidget()
        widget.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        column.addWidget(widget)
        parent.addLayout(column)
        return widget

    def _connect_signals(self) -> None:
        self._vm.experiments_changed.connect(self._on_experiments_changed)
        self._vm.experiment_selected.connect(self._on_experiment_selected)
        self._vm.preview_changed.connect(self._on_preview_changed)
        self._vm.analytics_started.connect(self._on_started)
        self._vm.analytics_completed.connect(self._on_completed)
        self._vm.analytics_failed.connect(self._on_failed)
        self._vm.error_occurred.connect(self._on_error)

    def _on_row_changed(self) -> None:
        rows = self._experiment_table.selectionModel().selectedRows()
        self._vm.select_experiment(rows[0].row() if rows else None)

    def _on_hosts_changed(self) -> None:
        self._vm.selected_hosts = [i.text() for i in self._hosts_list.selectedItems()]

    def _on_workloads_changed(self) -> None:
        self._vm.selected_workloads = [
            i.text() for i in self._workloads_list.selectedItems()
        ]

    def _on_experiments_changed(self, experiments: list) -> None:
        self._experiment_table.blockSignals(True)
        self._experiment_table.clearSelection()  # the VM dropped its selection
        self._experiment_table.blockSignals(False)
        rows = self._vm.get_experiment_rows()
        self._experiment_table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, cell in enumerate(row):
                self._experiment_table.setItem(i, j, QTableWidgetItem(cell))
        self._set_status(f"{len(experiments)} experiment(s) available", "muted")

    def _on_experiment_selected(self, experiment: ExperimentInfo | None) -> None:
        self._runs_list.clear()
        for widget, names in (
            (self._hosts_list, self._vm.available_hosts),
            (self._workloads_list, self._vm.available_workloads),
        ):
            widget.blockSignals(True)
            widget.clear()
            for name in names:
                item = QListWidgetItem(name)
                widget.addItem(item)
                item.setSelected(True)
            widget.blockSignals(False)
        if experiment is not None:
            for run in experiment.runs:
                self._runs_list.addItem(
                    f"{run.run_id}  {format_datetime(run.created_at)}  "
                    f"{', '.join(run.workloads)}"
                )
        self._sync_buttons()

    def _on_preview_changed(self, preview: UnificationPreview | None) -> None:
        rows = preview.summary_rows() if preview else []
        self._summary_table.setRowCount(len(rows))
        for i, (label, value) in enumerate(rows):
            self._summary_table.setItem(i, 0, QTableWidgetItem(label))
            self._summary_table.setItem(i, 1, QTableWidgetItem(value))
        self._progress.setVisible(False)
        self._sync_buttons()

    def _on_started(self) -> None:
        self._progress.setVisible(True)
        self._prepare_btn.setEnabled(False)
        self._unify_btn.setEnabled(False)
        self._set_status("Working...", "status-info")

    def _on_completed(self, paths: list) -> None:
        self._progress.setVisible(False)
        written = self._vm.last_written
        counts = written.row_counts if written else {}
        self._artifacts_list.clear()
        if written is not None:
            self._add_artifact(str(written.out_dir), written.out_dir)
            self._command_edit.setText(written.command)
        for path in paths:
            rows = counts.get(path.stem)
            label = f"{path.name} — {rows} rows" if rows is not None else path.name
            self._add_artifact(label, path)
        self._sync_buttons()
        self._set_status(f"Unified into {len(paths)} file(s)", "status-success")

    def _on_failed(self, error: str) -> None:
        self._progress.setVisible(False)
        self._sync_buttons()
        self._set_status(f"Failed: {error}", "status-error")

    def _on_error(self, message: str) -> None:
        self._set_status(message, "status-error")

    def _sync_buttons(self) -> None:
        idle = not self._vm.is_busy
        self._prepare_btn.setEnabled(idle and self._vm.selected_experiment is not None)
        self._unify_btn.setEnabled(idle and self._vm.can_unify)

    def _add_artifact(self, label: str, path: Path) -> None:
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, str(path))
        self._artifacts_list.addItem(item)

    def _set_status(self, text: str, role: str) -> None:
        self._status_label.setText(text)
        set_widget_role(self._status_label, role)

    def _on_artifact_double_clicked(self, item: QListWidgetItem) -> None:
        path = Path(item.data(Qt.ItemDataRole.UserRole) or item.text())
        if path.exists():
            self._open_path(path)
        else:
            QMessageBox.warning(
                self, "File Not Found", f"The file does not exist:\n{path}"
            )

    def _open_path(self, path: Path) -> None:
        """Open a path in the system file browser or application."""
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", str(path)])
            elif sys.platform == "win32":
                # os.startfile is the Windows API for "open with the default
                # application". The previous subprocess.run(["start", ...],
                # shell=True) needed a shell because `start` is a cmd.exe
                # builtin, which bandit flags (B602) and which passed the path
                # through a shell unnecessarily.
                os.startfile(path)
            else:
                subprocess.run(["xdg-open", str(path)])
        except Exception as e:
            QMessageBox.warning(
                self,
                "Error",
                f"Could not open file:\n{e}",
            )
