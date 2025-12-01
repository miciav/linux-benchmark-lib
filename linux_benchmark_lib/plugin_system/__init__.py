"""Core plugin system primitives (interfaces, registry, discovery)."""

from .interface import WorkloadPlugin, WorkloadIntensity
from .base_generator import BaseGenerator
from .registry import PluginRegistry, CollectorPlugin, print_plugin_table, USER_PLUGIN_DIR
from .builtin import builtin_plugins

__all__ = [
    "WorkloadPlugin",
    "WorkloadIntensity",
    "BaseGenerator",
    "PluginRegistry",
    "CollectorPlugin",
    "print_plugin_table",
    "USER_PLUGIN_DIR",
    "builtin_plugins",
]
