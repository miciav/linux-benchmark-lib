"""Plugin registry factory helpers."""

from plugins.builtin import builtin_plugins
from plugins.registry import PluginRegistry


def create_registry() -> PluginRegistry:
    """
    Build a plugin registry with built-ins and entry points.

    Entry points are loaded automatically by the registry; built-ins are
    explicitly registered to ensure a usable baseline even when entry point
    discovery is not available.
    """
    return PluginRegistry(builtin_plugins())
