"""Wrapper around lb_app.api.ConfigService."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from lb_app.api import ConfigService, BenchmarkConfig

if TYPE_CHECKING:
    from lb_app.api import PlatformConfig


class GUIConfigService:
    """Service for configuration management."""

    def __init__(self) -> None:
        self._service = ConfigService()
        self._current_config: BenchmarkConfig | None = None
        self._current_path: Path | None = None

    @property
    def service(self) -> ConfigService:
        """Access the underlying ConfigService."""
        return self._service

    def load_config(
        self, path: Path | None = None
    ) -> tuple[BenchmarkConfig, Path | None, Path | None]:
        """Load config for reading. Returns (config, resolved_path, saved_default_path)."""
        return self._service.load_for_read(path)

    def load_config_for_write(
        self, path: Path | None = None
    ) -> tuple[BenchmarkConfig, Path, Path | None, bool]:
        """Load config for writing. Returns (config, resolved_path, saved_path, existed)."""
        return self._service.load_for_write(path)

    def load_platform_config(self) -> tuple["PlatformConfig", Path, bool]:
        """Load platform config. Returns (config, path, existed)."""
        return self._service.load_platform_config()

    def set_plugin_enabled(self, name: str, enabled: bool) -> tuple["PlatformConfig", Path]:
        """Enable or disable a plugin in platform config."""
        return self._service.set_plugin_enabled(name, enabled)

    def get_saved_config_path(self) -> tuple[Path | None, Path | None]:
        """Get the saved default config path. Returns (saved_path, file_path)."""
        return self._service.read_saved_config_path()

    def set_saved_config_path(self, path: Path) -> None:
        """Set the default config path."""
        self._service.write_saved_config_path(path)

    def clear_saved_config_path(self) -> None:
        """Clear the saved default config path."""
        self._service.clear_saved_config_path()

    def set_current_config(
        self, config: BenchmarkConfig, path: Path | None
    ) -> None:
        """Store the most recently loaded config in memory."""
        self._current_config = config
        self._current_path = path

    def get_current_config(self) -> tuple[BenchmarkConfig | None, Path | None]:
        """Return the most recently loaded config, if any."""
        return self._current_config, self._current_path
