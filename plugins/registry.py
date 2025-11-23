"""
Registry and discovery utilities for workload plugins.

Plugins are small adapters that expose workload generators under a stable
interface. They can be registered programmatically or exposed via Python
entry points under the ``linux_benchmark.workloads`` group.
"""

from __future__ import annotations

import importlib.metadata
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Optional, Type

from workload_generators._base_generator import BaseGenerator


logger = logging.getLogger(__name__)
ENTRYPOINT_GROUP = "linux_benchmark.workloads"


@dataclass
class WorkloadPlugin:
    """Metadata and factory for a workload generator plugin."""

    name: str
    description: str
    config_cls: Type[Any]
    factory: Callable[[Any], BaseGenerator]

    def create_generator(self, options: Optional[Dict[str, Any]] = None) -> BaseGenerator:
        """
        Build a generator instance from the provided options.

        Args:
            options: Dictionary of configuration values. If absent, defaults
                from the config dataclass are used.
        """
        config_obj = self._build_config(options or {})
        return self.factory(config_obj)

    def _build_config(self, options: Dict[str, Any]) -> Any:
        """Instantiate the config dataclass from provided options."""
        if isinstance(options, self.config_cls):
            return options
        return self.config_cls(**options)


class PluginRegistry:
    """In-memory registry that supports built-in and external plugins."""

    def __init__(self, plugins: Optional[Iterable[WorkloadPlugin]] = None):
        self._plugins: Dict[str, WorkloadPlugin] = {}
        if plugins:
            for plugin in plugins:
                self.register(plugin)
        self._load_entrypoint_plugins()

    def register(self, plugin: WorkloadPlugin) -> None:
        """Register a new plugin, overriding any existing one with the same name."""
        self._plugins[plugin.name] = plugin

    def get(self, name: str) -> WorkloadPlugin:
        """Return a plugin by name or raise a KeyError."""
        if name not in self._plugins:
            raise KeyError(f"Plugin '{name}' not found")
        return self._plugins[name]

    def create_generator(
        self, plugin_name: str, options: Optional[Dict[str, Any]] = None
    ) -> BaseGenerator:
        """Create a generator instance using the selected plugin."""
        plugin = self.get(plugin_name)
        return plugin.create_generator(options or {})

    def available(self) -> Dict[str, WorkloadPlugin]:
        """Return the registered plugins keyed by name."""
        return dict(self._plugins)

    def _load_entrypoint_plugins(self) -> None:
        """Load plugins exposed via Python entry points."""
        try:
            eps = importlib.metadata.entry_points().select(group=ENTRYPOINT_GROUP)
        except Exception:
            return

        for entry_point in eps:
            try:
                plugin = entry_point.load()
            except Exception:
                continue
            if isinstance(plugin, WorkloadPlugin):
                self.register(plugin)


def print_plugin_table(
    registry: "PluginRegistry",
    enabled: Optional[Dict[str, bool]] = None,
) -> None:
    """
    Render the available plugins using Rich.

    This is a lightweight convenience wrapper to avoid duplicating table setup
    wherever we want to display the registered workloads.
    """
    try:
        from rich.console import Console
        from rich.table import Table
    except Exception:
        return

    try:
        console = Console()
        table = Table(
            title="Available Workload Plugins",
            header_style="bold cyan",
            show_edge=False,
        )
        table.add_column("Name", style="bold")
        if enabled is not None:
            table.add_column("Enabled", justify="center")
        table.add_column("Description")
        table.add_column("Config")
        for name, plugin in sorted(registry.available().items()):
            description = getattr(plugin, "description", "")
            if enabled is None:
                table.add_row(name, description, plugin.config_cls.__name__)
            else:
                status = enabled.get(name)
                if status is None:
                    status_str = "[yellow]?[/yellow]"
                elif status:
                    status_str = "[green]✓[/green]"
                else:
                    status_str = "[red]✗[/red]"
                table.add_row(name, status_str, description, plugin.config_cls.__name__)
        console.print(table)
    except Exception:
        logger.debug("Failed to render plugin list", exc_info=True)
