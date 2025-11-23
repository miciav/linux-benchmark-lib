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

from metric_collectors._base_collector import BaseCollector
from benchmark_config import BenchmarkConfig


logger = logging.getLogger(__name__)
ENTRYPOINT_GROUP = "linux_benchmark.workloads"
COLLECTOR_ENTRYPOINT_GROUP = "linux_benchmark.collectors"


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


@dataclass
class CollectorPlugin:
    """Metadata and factory for a metric collector plugin."""

    name: str
    description: str
    factory: Callable[[BenchmarkConfig], BaseCollector]
    should_run: Callable[[BenchmarkConfig], bool] = lambda _: True


class PluginRegistry:
    """In-memory registry that supports built-in and external plugins."""

    def __init__(self, plugins: Optional[Iterable[WorkloadPlugin | CollectorPlugin]] = None):
        self._workloads: Dict[str, WorkloadPlugin] = {}
        self._collectors: Dict[str, CollectorPlugin] = {}
        if plugins:
            for plugin in plugins:
                self.register(plugin)
        self._load_entrypoint_plugins()

    def register(self, plugin: WorkloadPlugin | CollectorPlugin) -> None:
        """Register a new plugin, overriding any existing one with the same name."""
        if isinstance(plugin, WorkloadPlugin):
            self._workloads[plugin.name] = plugin
        elif isinstance(plugin, CollectorPlugin):
            self._collectors[plugin.name] = plugin
        else:
            raise TypeError(f"Unknown plugin type: {type(plugin)}")

    def get(self, name: str) -> WorkloadPlugin:
        """Return a workload plugin by name or raise a KeyError."""
        if name not in self._workloads:
            raise KeyError(f"Workload Plugin '{name}' not found")
        return self._workloads[name]

    def get_collector(self, name: str) -> CollectorPlugin:
        """Return a collector plugin by name or raise a KeyError."""
        if name not in self._collectors:
            raise KeyError(f"Collector Plugin '{name}' not found")
        return self._collectors[name]

    def create_generator(
        self, plugin_name: str, options: Optional[Dict[str, Any]] = None
    ) -> BaseGenerator:
        """Create a generator instance using the selected plugin."""
        plugin = self.get(plugin_name)
        return plugin.create_generator(options or {})

    def create_collectors(self, config: BenchmarkConfig) -> list[BaseCollector]:
        """Create all enabled collector instances based on config."""
        collectors = []
        for plugin in self._collectors.values():
            if plugin.should_run(config):
                try:
                    collector = plugin.factory(config)
                    collectors.append(collector)
                except Exception as e:
                    logger.error(f"Failed to create collector {plugin.name}: {e}")
        return collectors

    def available(self) -> Dict[str, WorkloadPlugin]:
        """Return the registered workload plugins keyed by name."""
        return dict(self._workloads)
    
    def available_collectors(self) -> Dict[str, CollectorPlugin]:
        """Return the registered collector plugins keyed by name."""
        return dict(self._collectors)

    def _load_entrypoint_plugins(self) -> None:
        """Load plugins exposed via Python entry points."""
        for group in [ENTRYPOINT_GROUP, COLLECTOR_ENTRYPOINT_GROUP]:
            try:
                eps = importlib.metadata.entry_points().select(group=group)
            except Exception:
                continue

            for entry_point in eps:
                try:
                    plugin = entry_point.load()
                except Exception:
                    continue
                if isinstance(plugin, (WorkloadPlugin, CollectorPlugin)):
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
