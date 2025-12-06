"""
Registry and discovery utilities for workload plugins.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import logging
import os
import sys
import tomllib
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Optional, Type, Union

from ..metric_collectors._base_collector import BaseCollector
from .base_generator import BaseGenerator
from ..benchmark_config import BenchmarkConfig
from .interface import WorkloadPlugin as IWorkloadPlugin
from lb_ui.ui import get_ui_adapter
from lb_ui.ui.types import UIAdapter


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
    aggregator: Optional[Callable[[Any], Dict[str, float]]] = None
    should_run: Callable[[BenchmarkConfig], bool] = lambda _: True


class PluginRegistry:
    """In-memory registry that supports built-in, entry-point, and user directory plugins."""

    def __init__(self, plugins: Optional[Iterable[Any]] = None):
        self._workloads: Dict[str, IWorkloadPlugin] = {}
        self._collectors: Dict[str, CollectorPlugin] = {}
        self._pending_entrypoints: Dict[str, importlib.metadata.EntryPoint] = {}
        if plugins:
            for plugin in plugins:
                self.register(plugin)
        self._discover_entrypoint_plugins()
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
        if name not in self._workloads and name in self._pending_entrypoints:
            self._load_entrypoint(name)
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

    def available(self, load_entrypoints: bool = False) -> Dict[str, Any]:
        """
        Return available workload plugins.

        When load_entrypoints is True, pending entry-point plugins are resolved and
        registered; otherwise only already-registered plugins are returned.
        """
        if load_entrypoints:
            self._load_pending_entrypoints()
        return dict(self._workloads)
    
    def available_collectors(self) -> Dict[str, CollectorPlugin]:
        return dict(self._collectors)

    def _discover_entrypoint_plugins(self) -> None:
        """Collect entry points without importing them. Loaded on demand."""
        for group in [ENTRYPOINT_GROUP, COLLECTOR_ENTRYPOINT_GROUP]:
            try:
                eps = importlib.metadata.entry_points().select(group=group)
            except Exception:
                continue
            for entry_point in eps:
                self._pending_entrypoints.setdefault(entry_point.name, entry_point)

    def _load_pending_entrypoints(self) -> None:
        """Load all pending entry-point plugins."""
        names = list(self._pending_entrypoints.keys())
        for name in names:
            self._load_entrypoint(name)

    def _load_entrypoint(self, name: str) -> None:
        """Load a single entry-point plugin by name if pending."""
        entry_point = self._pending_entrypoints.pop(name, None)
        if not entry_point:
            return
        try:
            plugin = entry_point.load()
            self.register(plugin)
        except ImportError as exc:
            logger.debug(
                "Skipping plugin entry point %s due to missing dependency: %s",
                entry_point.name,
                exc,
            )
        except Exception as exc:
            logger.warning(f"Failed to load plugin entry point {entry_point.name}: {exc}")

    def _load_user_plugins(self) -> None:
        """Load python plugins from the user config directory."""
        if not USER_PLUGIN_DIR.exists():
            return

        # 1. Load individual .py files (legacy/simple mode)
        for path in USER_PLUGIN_DIR.glob("*.py"):
            if path.name.startswith("_"):
                continue
            self._load_plugin_from_path(path)

        # 2. Load plugins from subdirectories (complex mode with assets)
        for path in USER_PLUGIN_DIR.iterdir():
            if path.is_dir() and not path.name.startswith("_"):
                target = None
                
                # A. Try resolving via pyproject.toml
                toml_file = path / "pyproject.toml"
                if toml_file.exists():
                    target = self._resolve_entry_point_from_toml(path, toml_file)
                    if target:
                        logger.debug(f"Resolved plugin via pyproject.toml: {target}")

                # B. Fallback to heuristic scanning if TOML didn't yield a result
                if not target:
                    candidates = [
                        path / "__init__.py",
                        path / "plugin.py",
                        path / f"{path.name}.py",
                    ]
                    # Also check immediate subdirectories for package structures
                    for sub in path.iterdir():
                        if sub.is_dir() and not sub.name.startswith((".", "_", "tests")):
                            candidates.append(sub / "plugin.py")
                            candidates.append(sub / "__init__.py")
                    
                    for candidate in candidates:
                        if candidate.exists():
                            target = candidate
                            break

                if target:
                     # Use the parent folder name as module name if inside a subdir
                    module_name = path.name if target.parent == path else target.parent.name
                    self._load_plugin_from_path(target, module_name=module_name)
                else:
                    logger.debug(f"Skipping user plugin dir {path}: No suitable python entry point found.")

    def _resolve_entry_point_from_toml(self, root: Path, toml_path: Path) -> Optional[Path]:
        """Parse pyproject.toml to guess the package location."""
        try:
            with open(toml_path, "rb") as f:
                data = tomllib.load(f)
            
            project = data.get("project", {})
            name = project.get("name")
            if name:
                # Standardize name: my-plugin -> my_plugin
                pkg_name = name.replace("-", "_")
                
                # Check for src/pkg_name layout
                src_pkg = root / "src" / pkg_name
                if src_pkg.exists():
                     return src_pkg / "plugin.py" if (src_pkg / "plugin.py").exists() else src_pkg / "__init__.py"
                
                # Check for root pkg_name layout
                root_pkg = root / pkg_name
                if root_pkg.exists():
                     return root_pkg / "plugin.py" if (root_pkg / "plugin.py").exists() else root_pkg / "__init__.py"

        except Exception as e:
            logger.warning(f"Failed to parse {toml_path}: {e}")
        return None

    def _load_plugin_from_path(self, path: Path, module_name: Optional[str] = None) -> None:
        try:
            name = module_name or path.stem
            spec = importlib.util.spec_from_file_location(name, path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                sys.modules[name] = module
                try:
                    spec.loader.exec_module(module)
                except Exception as e:
                     logger.error(f"Error executing module {path}: {e}")
                     return

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
    for name, plugin in sorted(registry.available(load_entrypoints=True).items()):
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
