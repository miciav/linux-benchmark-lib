"""
Registry and discovery utilities for workload plugins.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import logging
import os
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Optional, Type, Union

from metric_collectors._base_collector import BaseCollector
from plugins.base_generator import BaseGenerator
from benchmark_config import BenchmarkConfig
from plugins.interface import WorkloadPlugin as IWorkloadPlugin
from ui import get_ui_adapter
from ui.types import UIAdapter


logger = logging.getLogger(__name__)
ENTRYPOINT_GROUP = "linux_benchmark.workloads"
COLLECTOR_ENTRYPOINT_GROUP = "linux_benchmark.collectors"
USER_PLUGIN_DIR = Path.home() / ".config" / "lb" / "plugins"


@dataclass
class CollectorPlugin:
    """Metadata and factory for a metric collector plugin."""
    name: str
    description: str
    factory: Callable[[BenchmarkConfig], BaseCollector]
    should_run: Callable[[BenchmarkConfig], bool] = lambda _: True


class PluginRegistry:
    """In-memory registry that supports built-in, entry-point, and user directory plugins."""

    def __init__(self, plugins: Optional[Iterable[Any]] = None):
        self._workloads: Dict[str, IWorkloadPlugin] = {}
        self._collectors: Dict[str, CollectorPlugin] = {}
        if plugins:
            for plugin in plugins:
                self.register(plugin)
        self._load_entrypoint_plugins()
        self._load_user_plugins()

    def register(self, plugin: Any) -> None:
        """Register a new plugin."""
        if isinstance(plugin, IWorkloadPlugin):
            self._workloads[plugin.name] = plugin
        elif isinstance(plugin, CollectorPlugin):
            self._collectors[plugin.name] = plugin
        else:
            # Try duck typing for IWorkloadPlugin if strict check fails (e.g. different import paths)
            if hasattr(plugin, "name") and hasattr(plugin, "create_generator"):
                self._workloads[plugin.name] = plugin
            else:
                raise TypeError(f"Unknown plugin type: {type(plugin)}")

    def get(self, name: str) -> IWorkloadPlugin:
        if name not in self._workloads:
            raise KeyError(f"Workload Plugin '{name}' not found")
        return self._workloads[name]

    def get_collector(self, name: str) -> CollectorPlugin:
        if name not in self._collectors:
            raise KeyError(f"Collector Plugin '{name}' not found")
        return self._collectors[name]

    def create_generator(
        self, plugin_name: str, options: Optional[Dict[str, Any]] = None
    ) -> BaseGenerator:
        plugin = self.get(plugin_name)
        
        # New style: we need to handle config instantiation here or in the plugin
        # The interface says `create_generator(config: Any)`.
        # We need to convert dict -> config_obj.
        
        if options is None:
            options = {}
            
        # If options is already the config object, pass it
        if isinstance(options, plugin.config_cls):
            return plugin.create_generator(options)
            
        # Otherwise instantiate from dict
        config_obj = plugin.config_cls(**options)
        return plugin.create_generator(config_obj)

    def create_collectors(self, config: BenchmarkConfig) -> list[BaseCollector]:
        collectors = []
        for plugin in self._collectors.values():
            if plugin.should_run(config):
                try:
                    collector = plugin.factory(config)
                    collectors.append(collector)
                except Exception as e:
                    logger.error(f"Failed to create collector {plugin.name}: {e}")
        return collectors

    def available(self) -> Dict[str, Any]:
        return dict(self._workloads)
    
    def available_collectors(self) -> Dict[str, CollectorPlugin]:
        return dict(self._collectors)

    def _load_entrypoint_plugins(self) -> None:
        for group in [ENTRYPOINT_GROUP, COLLECTOR_ENTRYPOINT_GROUP]:
            try:
                eps = importlib.metadata.entry_points().select(group=group)
            except Exception:
                continue
            for entry_point in eps:
                try:
                    plugin = entry_point.load()
                    self.register(plugin)
                except Exception as exc:
                    logger.warning(f"Failed to load plugin entry point {entry_point.name}: {exc}")

    def _load_user_plugins(self) -> None:
        """Load python plugins from the user config directory."""
        if not USER_PLUGIN_DIR.exists():
            return

        for path in USER_PLUGIN_DIR.glob("*.py"):
            if path.name.startswith("_"):
                continue
                
            try:
                spec = importlib.util.spec_from_file_location(path.stem, path)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[path.stem] = module
                    spec.loader.exec_module(module)
                    
                    # Look for 'PLUGIN' variable
                    if hasattr(module, "PLUGIN"):
                        self.register(module.PLUGIN)
                        logger.info(f"Loaded user plugin from {path}")
                    else:
                        logger.debug(f"Skipping {path}: No PLUGIN variable found")
            except Exception as e:
                logger.warning(f"Failed to load user plugin {path}: {e}")


def print_plugin_table(
    registry: "PluginRegistry",
    enabled: Optional[Dict[str, bool]] = None,
    ui_adapter: Optional[UIAdapter] = None,
) -> None:
    ui = ui_adapter or get_ui_adapter()
    rows = []
    for name, plugin in sorted(registry.available().items()):
        description = getattr(plugin, "description", "")
        config_name = plugin.config_cls.__name__
        if enabled is None:
            rows.append([name, description, config_name])
        else:
            status = "✓" if enabled.get(name) else "✗"
            rows.append([name, status, description, config_name])
            
    headers = ["Name", "Description", "Config"]
    if enabled is not None:
        headers.insert(1, "Enabled")
    ui.show_table("Available Workload Plugins", headers, rows)
