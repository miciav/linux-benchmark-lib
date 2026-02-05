"""Config view for viewing and managing benchmark configuration."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from lb_gui.utils import set_widget_role

if TYPE_CHECKING:
    from lb_gui.viewmodels.config_vm import ConfigViewModel


class ConfigView(QWidget):
    """View for viewing and managing benchmark configuration."""

    def __init__(
        self,
        viewmodel: "ConfigViewModel",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._vm = viewmodel

        self._setup_ui()
        self._connect_signals()
        self._vm.load_config()

    def _setup_ui(self) -> None:
        """Set up the UI layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Title
        title = QLabel("Configuration")
        title.setProperty("role", "title")
        layout.addWidget(title)

        # Load/Default buttons
        btn_layout = QHBoxLayout()

        load_btn = QPushButton("Load Config...")
        load_btn.clicked.connect(self._on_load)
        btn_layout.addWidget(load_btn)

        self._set_default_btn = QPushButton("Set as Default")
        self._set_default_btn.setEnabled(False)
        self._set_default_btn.clicked.connect(self._on_set_default)
        btn_layout.addWidget(self._set_default_btn)

        clear_default_btn = QPushButton("Clear Default")
        clear_default_btn.clicked.connect(self._on_clear_default)
        btn_layout.addWidget(clear_default_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # Current config path
        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("Loaded:"))
        self._path_label = QLabel("(none)")
        self._path_label.setProperty("role", "muted")
        path_layout.addWidget(self._path_label, 1)
        layout.addLayout(path_layout)

        # Default path
        default_layout = QHBoxLayout()
        default_layout.addWidget(QLabel("Default:"))
        self._default_label = QLabel("(not set)")
        self._default_label.setProperty("role", "muted")
        default_layout.addWidget(self._default_label, 1)
        layout.addLayout(default_layout)

        # Basic info group
        basic_group = QGroupBox("Basic Settings")
        self._basic_form = QFormLayout(basic_group)
        self._basic_labels: dict[str, QLabel] = {}
        for field in [
            "Repetitions",
            "Test Duration (s)",
            "Metrics Interval (s)",
            "Warmup (s)",
            "Cooldown (s)",
            "Output Directory",
            "Report Directory",
            "Export Directory",
        ]:
            label = QLabel("-")
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self._basic_labels[field] = label
            self._basic_form.addRow(f"{field}:", label)
        layout.addWidget(basic_group)

        # Remote hosts group
        hosts_group = QGroupBox("Remote Hosts")
        hosts_layout = QVBoxLayout(hosts_group)
        self._hosts_table = QTableWidget()
        self._hosts_table.setColumnCount(4)
        self._hosts_table.setHorizontalHeaderLabels(["Name", "Address", "Port", "User"])
        self._hosts_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._hosts_table.verticalHeader().setVisible(False)
        self._hosts_table.setAlternatingRowColors(True)
        self._hosts_table.setShowGrid(False)
        self._hosts_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        hosts_layout.addWidget(self._hosts_table)
        layout.addWidget(hosts_group)

        # Loki group
        loki_group = QGroupBox("Loki Configuration")
        self._loki_form = QFormLayout(loki_group)
        self._loki_labels: dict[str, QLabel] = {}
        for field in ["Enabled", "Endpoint", "Batch Size"]:
            label = QLabel("-")
            self._loki_labels[field] = label
            self._loki_form.addRow(f"{field}:", label)
        layout.addWidget(loki_group)

        # Status
        self._status_label = QLabel("")
        self._status_label.setProperty("role", "muted")
        layout.addWidget(self._status_label)

        layout.addStretch()

        # Update default label on startup
        self._update_default_label()

    def _connect_signals(self) -> None:
        """Connect viewmodel signals."""
        self._vm.config_loaded.connect(self._on_config_loaded)
        self._vm.error_occurred.connect(self._on_error)

    def _update_default_label(self) -> None:
        """Update the default path label."""
        default = self._vm.get_default_path()
        if default:
            self._default_label.setText(str(default))
            set_widget_role(self._default_label, None)
        else:
            self._default_label.setText("(not set)")
            set_widget_role(self._default_label, "muted")

    def _on_load(self) -> None:
        """Handle load button click."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Configuration",
            "",
            "YAML files (*.yaml *.yml);;JSON files (*.json);;All files (*)",
        )
        if path:
            self._vm.load_config(Path(path))

    def _on_set_default(self) -> None:
        """Handle set default button click."""
        if self._vm.set_as_default():
            self._status_label.setText("Set as default config")
            set_widget_role(self._status_label, "status-success")
            self._update_default_label()

    def _on_clear_default(self) -> None:
        """Handle clear default button click."""
        if self._vm.clear_default():
            self._status_label.setText("Default cleared")
            set_widget_role(self._status_label, "status-success")
            self._update_default_label()

    def _on_config_loaded(self, config: object) -> None:
        """Handle config loaded."""
        # Update path label
        if self._vm.config_path:
            self._path_label.setText(str(self._vm.config_path))
            set_widget_role(self._path_label, None)
        else:
            self._path_label.setText("(default)")
            set_widget_role(self._path_label, "muted")

        # Update basic info
        basic_info = self._vm.get_basic_info()
        for field, label in self._basic_labels.items():
            label.setText(basic_info.get(field, "-"))

        # Update hosts table
        hosts = self._vm.get_remote_hosts_info()
        self._hosts_table.setRowCount(len(hosts))
        for i, host in enumerate(hosts):
            self._hosts_table.setItem(i, 0, QTableWidgetItem(host["Name"]))
            self._hosts_table.setItem(i, 1, QTableWidgetItem(host["Address"]))
            self._hosts_table.setItem(i, 2, QTableWidgetItem(host["Port"]))
            self._hosts_table.setItem(i, 3, QTableWidgetItem(host["User"]))

        # Update Loki info
        loki_info = self._vm.get_loki_info()
        for field, label in self._loki_labels.items():
            label.setText(loki_info.get(field, "-"))

        # Enable set default button
        self._set_default_btn.setEnabled(True)

        self._status_label.setText("Configuration loaded")
        set_widget_role(self._status_label, "status-success")

    def _on_error(self, message: str) -> None:
        """Handle error from viewmodel."""
        self._status_label.setText(message)
        set_widget_role(self._status_label, "status-error")
