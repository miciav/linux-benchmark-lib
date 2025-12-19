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


logger = logging.getLogger(__name__)
ENTRYPOINT_GROUP = "linux_benchmark.workloads"
COLLECTOR_ENTRYPOINT_GROUP = "linux_benchmark.collectors"
BUILTIN_PLUGIN_ROOT = Path(__file__).resolve().parent.parent / "plugins"
LEGACY_USER_PLUGIN_DIR = Path.home() / ".config" / "lb" / "plugins"


def resolve_user_plugin_dir() -> Path:
    """
    Determine where third-party/user plugins should be installed and loaded from.

    Preference order:
    1) `LB_USER_PLUGIN_DIR` env override (if set).
    2) `<package>/plugins/_user` when writable (portable with runner tree).
    3) Legacy `~/.config/lb/plugins`.
    """
    override = os.environ.get("LB_USER_PLUGIN_DIR")
    if override:
        path = Path(override).expanduser().resolve()
        try:
            path.mkdir(parents=True, exist_ok=True)
        except Exception:
            # Directory creation may fail for read-only locations; caller handles.
            pass
        return path

    candidate = BUILTIN_PLUGIN_ROOT / "_user"
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        test_file = candidate / ".write_test"
        test_file.touch(exist_ok=True)
        test_file.unlink(missing_ok=True)
        return candidate
    except Exception:
        return LEGACY_USER_PLUGIN_DIR


USER_PLUGIN_DIR = resolve_user_plugin_dir()


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
            logger.warning(
                f"Failed to load plugin entry point {entry_point.name}: {exc}"
            )

    def _load_user_plugins(self) -> None:
        """Load python plugins from user plugin directories."""

        primary_dir = resolve_user_plugin_dir()
        if self._should_load_legacy(primary_dir):
            self._load_plugins_from_dir(LEGACY_USER_PLUGIN_DIR)
        self._load_plugins_from_dir(primary_dir)

    @staticmethod
    def _should_load_legacy(primary_dir: Path) -> bool:
        """Return True if legacy directory should also be scanned."""
        return (
            not os.environ.get("LB_USER_PLUGIN_DIR")
            and LEGACY_USER_PLUGIN_DIR != primary_dir
        )

    def _load_plugins_from_dir(self, root: Path) -> None:
        """Load plugins from a directory if it exists."""
        if not root.exists():
            return
        self._load_python_files(root)
        for path in self._iter_plugin_dirs(root):
            target = self._resolve_target_from_dir(path)
            if target:
                module_name = path.name if target.parent == path else target.parent.name
                self._load_plugin_from_path(target, module_name=module_name)
            else:
                logger.debug(
                    "Skipping user plugin dir %s: No suitable python entry point found.",
                    path,
                )

    def _load_python_files(self, root: Path) -> None:
        """Load top-level python modules that export PLUGIN/PLUGINS."""
        for path in root.glob("*.py"):
            if path.name.startswith("_"):
                continue
            self._load_plugin_from_path(path)

    @staticmethod
    def _iter_plugin_dirs(root: Path) -> Iterable[Path]:
        """Yield plugin directory candidates under root."""
        return (
            path
            for path in root.iterdir()
            if path.is_dir() and not path.name.startswith("_")
        )

    def _resolve_target_from_dir(self, path: Path) -> Optional[Path]:
        """Resolve a plugin entry point within a plugin directory."""
        toml_file = path / "pyproject.toml"
        if toml_file.exists():
            target = self._resolve_entry_point_from_toml(path, toml_file)
            if target:
                logger.debug(f"Resolved plugin via pyproject.toml: {target}")
                return target
        for candidate in self._candidate_entrypoints(path):
            if candidate.exists():
                return candidate
        return None

    @staticmethod
    def _candidate_entrypoints(path: Path) -> Iterable[Path]:
        """Return likely plugin module paths in a plugin directory."""
        candidates = [
            path / "__init__.py",
            path / "plugin.py",
            path / f"{path.name}.py",
        ]
        for sub in path.iterdir():
            if sub.is_dir() and not sub.name.startswith((".", "_", "tests")):
                candidates.append(sub / "plugin.py")
                candidates.append(sub / "__init__.py")
        return candidates

    def _resolve_entry_point_from_toml(
        self, root: Path, toml_path: Path
    ) -> Optional[Path]:
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
                    return (
                        src_pkg / "plugin.py"
                        if (src_pkg / "plugin.py").exists()
                        else src_pkg / "__init__.py"
                    )

                # Check for root pkg_name layout
                root_pkg = root / pkg_name
                if root_pkg.exists():
                    return (
                        root_pkg / "plugin.py"
                        if (root_pkg / "plugin.py").exists()
                        else root_pkg / "__init__.py"
                    )

        except Exception as e:
            logger.warning(f"Failed to parse {toml_path}: {e}")
        return None

    def _load_plugin_from_path(
        self, path: Path, module_name: Optional[str] = None
    ) -> None:
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

                self._register_from_module(module, source=str(path))
        except Exception as e:
            logger.warning(f"Failed to load user plugin {path}: {e}")

    def _register_from_module(self, module: Any, source: str) -> None:
        """Register PLUGIN / PLUGINS / get_plugins() exports from a python module."""
        try:
            if hasattr(module, "get_plugins") and callable(
                getattr(module, "get_plugins")
            ):
                discovered = module.get_plugins()
                candidates = (
                    discovered if isinstance(discovered, list) else [discovered]
                )
            elif hasattr(module, "PLUGINS"):
                discovered = getattr(module, "PLUGINS")
                candidates = (
                    discovered if isinstance(discovered, list) else [discovered]
                )
            elif hasattr(module, "PLUGIN"):
                candidates = [getattr(module, "PLUGIN")]
            else:
                logger.debug(
                    "Skipping %s: no PLUGIN/PLUGINS/get_plugins exports found", source
                )
                return

            registered = 0
            for plugin in candidates:
                if plugin is None:
                    continue
                self.register(plugin)
                registered += 1
            if registered:
                logger.info("Loaded %s plugin(s) from %s", registered, source)
            else:
                logger.debug("Skipping %s: exported plugin list was empty", source)
        except Exception as exc:
            logger.warning("Failed to register plugins from %s: %s", source, exc)
