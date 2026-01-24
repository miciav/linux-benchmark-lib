"""ViewModel for Plugins view."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

if TYPE_CHECKING:
    from lb_gui.services import PluginService, GUIConfigService


class PluginsViewModel(QObject):
    """ViewModel for the Plugins view.

    Manages plugin listing and enable/disable state.
    """

    # Signals
    plugins_changed = Signal(list, list)  # headers, rows
    plugin_toggled = Signal(str, bool)  # name, enabled
    error_occurred = Signal(str)

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
        self._headers: list[str] = []
        self._rows: list[list[str]] = []
        self._enabled_map: dict[str, bool] = {}

    @property
    def headers(self) -> list[str]:
        """Table headers."""
        return self._headers

    @property
    def rows(self) -> list[list[str]]:
        """Table rows."""
        return self._rows

    def refresh_plugins(self) -> None:
        """Refresh the plugin list."""
        try:
            platform_config, _, _ = self._config_service.load_platform_config()
            headers, rows = self._plugin_service.get_plugin_table(platform_config)

            # Build enabled map from rows (assuming first column is name)
            registry = self._plugin_service.get_registry()
            self._enabled_map = {
                name: platform_config.is_plugin_enabled(name)
                for name in registry.available()
            }

            self._headers = headers
            self._rows = rows
            self.plugins_changed.emit(headers, rows)
        except Exception as e:
            self.error_occurred.emit(f"Failed to load plugins: {e}")

    def toggle_plugin(self, name: str) -> None:
        """Toggle a plugin's enabled state."""
        try:
            current = self._enabled_map.get(name, True)
            new_state = not current
            self._config_service.set_plugin_enabled(name, new_state)
            self._enabled_map[name] = new_state
            self.plugin_toggled.emit(name, new_state)
            # Refresh to get updated table
            self.refresh_plugins()
        except Exception as e:
            self.error_occurred.emit(f"Failed to toggle plugin: {e}")

    def enable_plugin(self, name: str) -> None:
        """Enable a plugin."""
        if not self._enabled_map.get(name, False):
            self.toggle_plugin(name)

    def disable_plugin(self, name: str) -> None:
        """Disable a plugin."""
        if self._enabled_map.get(name, True):
            self.toggle_plugin(name)

    def is_plugin_enabled(self, name: str) -> bool:
        """Check if a plugin is enabled."""
        return self._enabled_map.get(name, True)

    def get_plugin_names(self) -> list[str]:
        """Get list of all plugin names."""
        return list(self._enabled_map.keys())
