"""Plugin management service."""

from __future__ import annotations

from typing import TYPE_CHECKING

from lb_app.api import (
    PluginRegistry,
    build_plugin_table,
    create_registry,
    reset_registry_cache,
)

if TYPE_CHECKING:
    from lb_app.api import PlatformConfig


class PluginService:
    """Service for plugin discovery and management."""

    def __init__(self) -> None:
        self._registry: PluginRegistry | None = None

    def get_registry(self, refresh: bool = False) -> PluginRegistry:
        """Get the plugin registry, optionally refreshing the cache."""
        if refresh or self._registry is None:
            reset_registry_cache()
            self._registry = create_registry(refresh=True)
        return self._registry

    def list_plugins(self) -> dict[str, bool]:
        """List all available plugins. Returns {name: is_available}."""
        registry = self.get_registry()
        return {name: True for name in registry.available()}

    def get_plugin_table(
        self, platform_config: "PlatformConfig"
    ) -> tuple[list[str], list[list[str]]]:
        """Get plugin table data for display.

        Returns (headers, rows) where each row contains plugin info.
        """
        registry = self.get_registry()
        enabled_map = {
            name: platform_config.is_plugin_enabled(name)
            for name in registry.available()
        }
        return build_plugin_table(registry, enabled=enabled_map)

    def is_plugin_available(self, name: str) -> bool:
        """Check if a plugin is available (installed)."""
        registry = self.get_registry()
        return name in registry.available()

    def refresh(self) -> None:
        """Force refresh the plugin registry cache."""
        self._registry = None
        self.get_registry(refresh=True)
