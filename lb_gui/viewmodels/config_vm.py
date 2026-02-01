"""ViewModel for Config view."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

from lb_gui.utils import format_optional

if TYPE_CHECKING:
    from lb_app.api import BenchmarkConfig
    from lb_gui.services import GUIConfigService


class ConfigViewModel(QObject):
    """ViewModel for the Config view.

    Manages loading, viewing, and saving benchmark configuration.
    """

    # Signals
    config_loaded = Signal(object)  # BenchmarkConfig
    config_saved = Signal(str)  # saved path
    error_occurred = Signal(str)

    def __init__(
        self,
        config_service: "GUIConfigService",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._config_service = config_service

        # State
        self._config: "BenchmarkConfig | None" = None
        self._config_path: Path | None = None
        self._is_dirty: bool = False

    @property
    def config(self) -> "BenchmarkConfig | None":
        """Current loaded configuration."""
        return self._config

    @property
    def config_path(self) -> Path | None:
        """Path of the loaded configuration."""
        return self._config_path

    @property
    def is_dirty(self) -> bool:
        """Whether config has unsaved changes."""
        return self._is_dirty

    @property
    def is_loaded(self) -> bool:
        """Whether a config is currently loaded."""
        return self._config is not None

    def load_config(self, path: Path | None = None) -> bool:
        """Load configuration from path or default.

        Returns True if successful.
        """
        try:
            config, resolved, _ = self._config_service.load_config(path)
            self._config = config
            self._config_path = resolved
            self._config_service.set_current_config(config, resolved)
            self._is_dirty = False
            self.config_loaded.emit(config)
            return True
        except Exception as e:
            self.error_occurred.emit(f"Failed to load config: {e}")
            return False

    def get_basic_info(self) -> dict[str, str]:
        """Get basic config info for display."""
        if self._config is None:
            return {}

        return {
            "Repetitions": str(self._config.repetitions),
            "Test Duration (s)": str(self._config.test_duration_seconds),
            "Metrics Interval (s)": str(self._config.metrics_interval_seconds),
            "Warmup (s)": str(self._config.warmup_seconds),
            "Cooldown (s)": str(self._config.cooldown_seconds),
            "Output Directory": format_optional(self._config.output_dir),
            "Report Directory": format_optional(self._config.report_dir),
            "Export Directory": format_optional(self._config.data_export_dir),
        }

    def get_remote_hosts_info(self) -> list[dict[str, str]]:
        """Get remote hosts info for display."""
        if self._config is None:
            return []

        hosts = []
        for host in self._config.remote_hosts:
            hosts.append({
                "Name": host.name,
                "Address": host.address,
                "Port": str(host.port),
                "User": host.user,
            })
        return hosts

    def get_loki_info(self) -> dict[str, str]:
        """Get Loki config info for display."""
        if self._config is None:
            return {}

        loki = self._config.loki
        return {
            "Enabled": "Yes" if loki.enabled else "No",
            "Endpoint": loki.endpoint,
            "Batch Size": str(loki.batch_size),
        }

    def set_as_default(self) -> bool:
        """Set the current config path as the default.

        Returns True if successful.
        """
        if self._config_path is None:
            self.error_occurred.emit("No config loaded to set as default")
            return False

        try:
            self._config_service.set_saved_config_path(self._config_path)
            return True
        except Exception as e:
            self.error_occurred.emit(f"Failed to set default: {e}")
            return False

    def clear_default(self) -> bool:
        """Clear the default config path.

        Returns True if successful.
        """
        try:
            self._config_service.clear_saved_config_path()
            return True
        except Exception as e:
            self.error_occurred.emit(f"Failed to clear default: {e}")
            return False

    def get_default_path(self) -> Path | None:
        """Get the saved default config path."""
        try:
            path, _ = self._config_service.get_saved_config_path()
            return path
        except Exception:
            return None
