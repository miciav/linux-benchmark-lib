"""Plugins view for managing workload plugins."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
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
    from lb_gui.viewmodels.plugins_vm import PluginsViewModel


class PluginsView(QWidget):
    """View for managing workload plugins."""

    def __init__(
        self,
        viewmodel: "PluginsViewModel",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._vm = viewmodel

        self._setup_ui()
        self._connect_signals()
        self._vm.refresh_plugins()

    def _setup_ui(self) -> None:
        """Set up the UI layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Title
        title = QLabel("Plugins")
        title.setProperty("role", "title")
        layout.addWidget(title)

        # Buttons
        btn_layout = QHBoxLayout()

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._on_refresh)
        btn_layout.addWidget(refresh_btn)

        self._enable_btn = QPushButton("Enable")
        self._enable_btn.setEnabled(False)
        self._enable_btn.clicked.connect(self._on_enable)
        btn_layout.addWidget(self._enable_btn)

        self._disable_btn = QPushButton("Disable")
        self._disable_btn.setEnabled(False)
        self._disable_btn.clicked.connect(self._on_disable)
        btn_layout.addWidget(self._disable_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # Plugin table
        self._table = QTableWidget()
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._table.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self._table, 1)

        # Status
        self._status_label = QLabel("")
        self._status_label.setProperty("role", "muted")
        layout.addWidget(self._status_label)

    def _connect_signals(self) -> None:
        """Connect viewmodel signals."""
        self._vm.plugins_changed.connect(self._on_plugins_changed)
        self._vm.plugin_toggled.connect(self._on_plugin_toggled)
        self._vm.error_occurred.connect(self._on_error)

    def _on_refresh(self) -> None:
        """Handle refresh button click."""
        self._vm.refresh_plugins()

    def _on_enable(self) -> None:
        """Handle enable button click."""
        name = self._get_selected_plugin_name()
        if name:
            self._vm.enable_plugin(name)

    def _on_disable(self) -> None:
        """Handle disable button click."""
        name = self._get_selected_plugin_name()
        if name:
            self._vm.disable_plugin(name)

    def _on_double_click(self, item: QTableWidgetItem) -> None:
        """Handle table double-click to toggle."""
        name = self._get_selected_plugin_name()
        if name:
            self._vm.toggle_plugin(name)

    def _on_selection_changed(self) -> None:
        """Handle table selection change."""
        name = self._get_selected_plugin_name()
        if name:
            is_enabled = self._vm.is_plugin_enabled(name)
            self._enable_btn.setEnabled(not is_enabled)
            self._disable_btn.setEnabled(is_enabled)
        else:
            self._enable_btn.setEnabled(False)
            self._disable_btn.setEnabled(False)

    def _get_selected_plugin_name(self) -> str | None:
        """Get the name of the selected plugin."""
        selected = self._table.selectedItems()
        if selected:
            row = selected[0].row()
            name_item = self._table.item(row, 0)
            if name_item:
                return name_item.text()
        return None

    def _on_plugins_changed(self, headers: list[str], rows: list[list[str]]) -> None:
        """Handle plugins list update."""
        self._table.setColumnCount(len(headers))
        self._table.setHorizontalHeaderLabels(headers)
        self._table.setRowCount(len(rows))

        for i, row in enumerate(rows):
            for j, cell in enumerate(row):
                item = QTableWidgetItem(str(cell))
                # Color-code enabled column if present
                if headers[j].lower() == "enabled":
                    if cell.lower() in ("yes", "true", "enabled"):
                        item.setForeground(Qt.GlobalColor.darkGreen)
                    else:
                        item.setForeground(Qt.GlobalColor.gray)
                self._table.setItem(i, j, item)

        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setStretchLastSection(True)

        self._status_label.setText(f"{len(rows)} plugin(s) available")
        set_widget_role(self._status_label, "muted")

    def _on_plugin_toggled(self, name: str, enabled: bool) -> None:
        """Handle plugin toggle."""
        state = "enabled" if enabled else "disabled"
        self._status_label.setText(f"Plugin '{name}' {state}")
        set_widget_role(self._status_label, "status-success")
        self._on_selection_changed()

    def _on_error(self, message: str) -> None:
        """Handle error from viewmodel."""
        self._status_label.setText(message)
        set_widget_role(self._status_label, "status-error")
