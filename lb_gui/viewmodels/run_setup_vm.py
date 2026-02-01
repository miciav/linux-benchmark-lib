"""ViewModel for Run Setup view."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

from lb_app.api import (
    BenchmarkConfig,
    MAX_NODES,
    RunRequest,
    WorkloadIntensity,
)

if TYPE_CHECKING:
    from lb_gui.services import PluginService, GUIConfigService


class RunSetupViewModel(QObject):
    """ViewModel for the Run Setup view.

    Manages state for workload selection, execution parameters,
    and run request construction.
    """

    # Signals for state changes
    workloads_changed = Signal(list)  # list of available workload names
    config_changed = Signal(object)  # BenchmarkConfig
    validation_changed = Signal(bool, str)  # (is_valid, error_message)

    # Execution modes
    EXECUTION_MODES = ["remote", "docker", "multipass"]

    # Intensity options
    INTENSITY_OPTIONS = ["low", "medium", "high", "user_defined"]

    def __init__(
        self,
        plugin_service: "PluginService",
        config_service: "GUIConfigService",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._plugin_service = plugin_service
        self._config_service = config_service

        # State
        self._config: BenchmarkConfig | None = None
        self._available_workloads: list[str] = []
        self._selected_workloads: list[str] = []
        self._intensity: str = "medium"
        self._repetitions: int = 1
        self._run_id: str = ""
        self._stop_file: str = ""
        self._execution_mode: str = "remote"
        self._node_count: int = 1

    @property
    def config(self) -> BenchmarkConfig | None:
        """Current benchmark configuration."""
        return self._config

    @property
    def available_workloads(self) -> list[str]:
        """List of available workload names."""
        return self._available_workloads

    @property
    def selected_workloads(self) -> list[str]:
        """Currently selected workloads."""
        return self._selected_workloads

    @selected_workloads.setter
    def selected_workloads(self, value: list[str]) -> None:
        self._selected_workloads = value
        self._emit_validation()

    @property
    def intensity(self) -> str:
        """Selected intensity level."""
        return self._intensity

    @intensity.setter
    def intensity(self, value: str) -> None:
        if value in self.INTENSITY_OPTIONS:
            self._intensity = value

    @property
    def repetitions(self) -> int:
        """Number of repetitions."""
        return self._repetitions

    @repetitions.setter
    def repetitions(self, value: int) -> None:
        self._repetitions = max(1, value)

    @property
    def run_id(self) -> str:
        """Custom run ID (empty for auto-generated)."""
        return self._run_id

    @run_id.setter
    def run_id(self, value: str) -> None:
        self._run_id = value.strip()

    @property
    def stop_file(self) -> str:
        """Path to stop file (empty for none)."""
        return self._stop_file

    @stop_file.setter
    def stop_file(self, value: str) -> None:
        self._stop_file = value.strip()

    @property
    def execution_mode(self) -> str:
        """Execution mode (remote/docker/multipass)."""
        return self._execution_mode

    @execution_mode.setter
    def execution_mode(self, value: str) -> None:
        if value in self.EXECUTION_MODES:
            self._execution_mode = value
            self._emit_validation()

    @property
    def node_count(self) -> int:
        """Number of nodes for docker/multipass modes."""
        return self._node_count

    @node_count.setter
    def node_count(self, value: int) -> None:
        self._node_count = max(1, min(value, MAX_NODES))

    @property
    def node_count_enabled(self) -> bool:
        """Whether node count input should be enabled."""
        return self._execution_mode in ("docker", "multipass")

    @property
    def max_nodes(self) -> int:
        """Maximum allowed node count."""
        return MAX_NODES

    def load_config(self, path: Path | None = None) -> bool:
        """Load benchmark configuration.

        Returns True if successful, False otherwise.
        """
        if path is None:
            cached, _ = self._config_service.get_current_config()
            if cached is not None:
                self.set_config(cached)
                return True
        try:
            config, resolved_path, _ = self._config_service.load_config(path)
            self._config_service.set_current_config(config, resolved_path)
            self.set_config(config)
            return True
        except Exception:
            self._config = None
            self.config_changed.emit(None)
            self._emit_validation()
            return False

    def set_config(self, config: BenchmarkConfig | None) -> None:
        """Set the current config directly."""
        self._config = config
        if config is not None:
            self._apply_config_defaults(config)
        self.config_changed.emit(config)
        self._emit_validation()

    def _apply_config_defaults(self, config: BenchmarkConfig) -> None:
        """Apply defaults from a loaded config to the viewmodel."""
        self._repetitions = max(1, int(config.repetitions))

        selected: list[str] = []
        intensities: set[str] = set()
        for name, workload in config.workloads.items():
            if getattr(workload, "enabled", True):
                selected.append(name)
                intensity = getattr(workload, "intensity", None)
                if isinstance(intensity, str):
                    intensities.add(intensity)

        self._selected_workloads = sorted(selected)
        if len(intensities) == 1:
            intensity = intensities.pop()
            if intensity in self.INTENSITY_OPTIONS:
                self._intensity = intensity
            else:
                self._intensity = "user_defined"
        elif intensities:
            self._intensity = "user_defined"

        if config.remote_hosts:
            self._execution_mode = "remote"

    def refresh_workloads(self) -> None:
        """Refresh the list of available workloads."""
        try:
            platform_config, _, _ = self._config_service.load_platform_config()
            registry = self._plugin_service.get_registry()

            # Get enabled workloads
            available_registry = registry.available()
            enabled = {
                name for name in available_registry
                if platform_config.is_plugin_enabled(name)
            }
            from_config = set()
            if self._config is not None:
                from_config = {name for name in self._config.workloads.keys()}
            available = enabled | from_config
            self._available_workloads = [
                name for name in available if name in available_registry
            ]
            self._available_workloads.sort()

            # Remove any selected workloads that are no longer available
            self._selected_workloads = [
                w for w in self._selected_workloads if w in self._available_workloads
            ]

            self.workloads_changed.emit(self._available_workloads)
            self._emit_validation()
        except Exception:
            self._available_workloads = []
            self.workloads_changed.emit([])
            self._emit_validation()

    def validate(self) -> tuple[bool, str]:
        """Validate current state for starting a run.

        Returns (is_valid, error_message).
        """
        if self._config is None:
            return False, "No configuration loaded"

        if not self._selected_workloads:
            return False, "No workloads selected"

        if self._execution_mode == "remote":
            # Remote mode requires configured hosts
            if not self._config.remote_hosts:
                return False, "No remote hosts configured"

        return True, ""

    def _emit_validation(self) -> None:
        """Emit validation state change."""
        is_valid, error = self.validate()
        self.validation_changed.emit(is_valid, error)

    def build_run_request(self) -> RunRequest | None:
        """Build a RunRequest from current state.

        Returns None if validation fails.
        """
        is_valid, _ = self.validate()
        if not is_valid or self._config is None:
            return None

        return RunRequest(
            config=self._config,
            tests=self._selected_workloads,
            run_id=self._run_id or None,
            intensity=self._intensity if self._intensity != "user_defined" else None,
            repetitions=self._repetitions,
            execution_mode=self._execution_mode,
            node_count=self._node_count,
            stop_file=Path(self._stop_file) if self._stop_file else None,
        )
