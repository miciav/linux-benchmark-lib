"""Run Setup view for configuring and starting benchmark runs."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from lb_gui.widgets import FilePicker
from lb_gui.utils import set_widget_role

if TYPE_CHECKING:
    from lb_gui.viewmodels.run_setup_vm import RunSetupViewModel


class RunSetupView(QWidget):
    """View for setting up and starting benchmark runs."""

    # Signal emitted when user clicks Start
    start_run_requested = Signal(object)  # RunRequest

    def __init__(
        self,
        viewmodel: "RunSetupViewModel",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._vm = viewmodel

        self._setup_ui()
        self._connect_signals()
        self._sync_from_viewmodel()
        self._initial_load()

    def _initial_load(self) -> None:
        """Load config and workloads on first render."""
        self._vm.load_config()
        self._vm.refresh_workloads()

    def _setup_ui(self) -> None:
        """Set up the UI layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Title
        title = QLabel("Run Setup")
        title.setProperty("role", "title")
        layout.addWidget(title)

        # Main content in horizontal layout
        content_layout = QHBoxLayout()
        content_layout.setSpacing(20)

        # Left side: Workload selection
        workload_group = self._create_workload_group()
        content_layout.addWidget(workload_group, 1)

        # Right side: Parameters
        params_group = self._create_params_group()
        content_layout.addWidget(params_group, 1)

        layout.addLayout(content_layout, 1)

        # Bottom: Status and Start button
        bottom_layout = self._create_bottom_layout()
        layout.addLayout(bottom_layout)

    def _create_workload_group(self) -> QGroupBox:
        """Create the workload selection group."""
        group = QGroupBox("Workloads")
        layout = QVBoxLayout(group)

        # Refresh button
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._on_refresh_workloads)
        layout.addWidget(refresh_btn)

        # Load Config button
        load_btn = QPushButton("Load Config...")
        load_btn.clicked.connect(self._on_load_config)
        layout.addWidget(load_btn)

        # Workload list (multi-select)
        self._workload_list = QListWidget()
        self._workload_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self._workload_list.itemSelectionChanged.connect(self._on_workload_selection_changed)
        layout.addWidget(self._workload_list)

        # Selection info
        self._selection_label = QLabel("0 workloads selected")
        self._selection_label.setProperty("role", "muted")
        layout.addWidget(self._selection_label)

        return group

    def _create_params_group(self) -> QGroupBox:
        """Create the parameters group."""
        group = QGroupBox("Parameters")
        layout = QFormLayout(group)
        layout.setSpacing(12)

        # Intensity
        self._intensity_combo = QComboBox()
        self._intensity_combo.addItems(["low", "medium", "high", "user_defined"])
        self._intensity_combo.setCurrentText("medium")
        self._intensity_combo.currentTextChanged.connect(self._on_intensity_changed)
        layout.addRow("Intensity:", self._intensity_combo)

        # Repetitions
        self._repetitions_spin = QSpinBox()
        self._repetitions_spin.setRange(1, 100)
        self._repetitions_spin.setValue(1)
        self._repetitions_spin.valueChanged.connect(self._on_repetitions_changed)
        layout.addRow("Repetitions:", self._repetitions_spin)

        # Run ID (optional)
        self._run_id_edit = QLineEdit()
        self._run_id_edit.setPlaceholderText("Auto-generated if empty")
        self._run_id_edit.textChanged.connect(self._on_run_id_changed)
        layout.addRow("Run ID:", self._run_id_edit)

        # Execution mode
        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["remote", "docker", "multipass"])
        self._mode_combo.currentTextChanged.connect(self._on_mode_changed)
        layout.addRow("Execution Mode:", self._mode_combo)

        # Node count (for docker/multipass)
        self._node_count_spin = QSpinBox()
        self._node_count_spin.setRange(1, self._vm.max_nodes)
        self._node_count_spin.setValue(1)
        self._node_count_spin.setEnabled(False)
        self._node_count_spin.valueChanged.connect(self._on_node_count_changed)
        layout.addRow("Node Count:", self._node_count_spin)

        # Stop file (optional)
        self._stop_file_picker = FilePicker(
            placeholder="Optional: path to stop file",
            dialog_title="Select stop file",
            mode="open",
        )
        self._stop_file_picker.path_changed.connect(self._on_stop_file_changed)
        layout.addRow("Stop File:", self._stop_file_picker)

        return group

    def _create_bottom_layout(self) -> QHBoxLayout:
        """Create the bottom status and button layout."""
        layout = QHBoxLayout()

        # Status label
        self._status_label = QLabel("")
        set_widget_role(self._status_label, "muted")
        layout.addWidget(self._status_label, 1)

        # Start button
        self._start_btn = QPushButton("Start Run")
        self._start_btn.setEnabled(False)
        self._start_btn.setMinimumWidth(120)
        self._start_btn.clicked.connect(self._on_start_clicked)
        layout.addWidget(self._start_btn)

        return layout

    def _connect_signals(self) -> None:
        """Connect viewmodel signals."""
        self._vm.workloads_changed.connect(self._on_workloads_changed)
        self._vm.validation_changed.connect(self._on_validation_changed)
        self._vm.config_changed.connect(self._on_config_changed)

    def _sync_from_viewmodel(self) -> None:
        """Sync UI state from viewmodel."""
        self._intensity_combo.setCurrentText(self._vm.intensity)
        self._repetitions_spin.setValue(self._vm.repetitions)
        self._run_id_edit.setText(self._vm.run_id)
        self._mode_combo.setCurrentText(self._vm.execution_mode)
        self._node_count_spin.setValue(self._vm.node_count)
        self._node_count_spin.setEnabled(self._vm.node_count_enabled)
        self._stop_file_picker.set_path(self._vm.stop_file)

    # Slots for UI events

    def _on_refresh_workloads(self) -> None:
        """Handle refresh button click."""
        self._vm.refresh_workloads()

    def _on_load_config(self) -> None:
        """Handle load config button click."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Configuration",
            "",
            "YAML files (*.yaml *.yml);;JSON files (*.json);;All files (*)",
        )
        if path:
            self._vm.load_config(Path(path))
            self._vm.refresh_workloads()

    def _on_workload_selection_changed(self) -> None:
        """Handle workload selection change."""
        selected = [item.text() for item in self._workload_list.selectedItems()]
        self._vm.selected_workloads = selected
        self._selection_label.setText(f"{len(selected)} workload(s) selected")

    def _on_intensity_changed(self, value: str) -> None:
        """Handle intensity combo change."""
        self._vm.intensity = value

    def _on_repetitions_changed(self, value: int) -> None:
        """Handle repetitions spinbox change."""
        self._vm.repetitions = value

    def _on_run_id_changed(self, value: str) -> None:
        """Handle run ID edit change."""
        self._vm.run_id = value

    def _on_mode_changed(self, value: str) -> None:
        """Handle execution mode change."""
        self._vm.execution_mode = value
        self._node_count_spin.setEnabled(self._vm.node_count_enabled)

    def _on_node_count_changed(self, value: int) -> None:
        """Handle node count change."""
        self._vm.node_count = value

    def _on_stop_file_changed(self, value: str) -> None:
        """Handle stop file edit change."""
        self._vm.stop_file = value

    def _on_start_clicked(self) -> None:
        """Handle start button click."""
        request = self._vm.build_run_request()
        if request is None:
            QMessageBox.warning(
                self,
                "Cannot Start Run",
                "Please ensure all parameters are valid.",
            )
            return
        self.start_run_requested.emit(request)

    # Slots for viewmodel signals

    def _on_workloads_changed(self, workloads: list[str]) -> None:
        """Handle workloads list update."""
        self._workload_list.clear()
        for name in workloads:
            item = QListWidgetItem(name)
            self._workload_list.addItem(item)
            # Restore selection if previously selected
            if name in self._vm.selected_workloads:
                item.setSelected(True)

    def _on_validation_changed(self, is_valid: bool, error: str) -> None:
        """Handle validation state change."""
        self._start_btn.setEnabled(is_valid)
        if error:
            self._status_label.setText(error)
            set_widget_role(self._status_label, "status-error")
        else:
            self._status_label.setText("Ready to start")
            set_widget_role(self._status_label, "status-success")

    def _on_config_changed(self, config: object) -> None:
        """Handle config change."""
        if config is None:
            self._status_label.setText("No configuration loaded")
            set_widget_role(self._status_label, "status-warning")
            return
        self._sync_from_viewmodel()
        self._selection_label.setText(
            f"{len(self._vm.selected_workloads)} workload(s) selected"
        )
