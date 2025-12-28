"""
Registry and discovery utilities for workload plugins.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from lb_common.entrypoints import (
    discover_entrypoints,
    load_entrypoint,
    load_pending_entrypoints,
)
from .base_generator import BaseGenerator
from .interface import WorkloadPlugin as IWorkloadPlugin
from .user_plugins import load_plugins_from_dir


logger = logging.getLogger(__name__)
ENTRYPOINT_GROUP = "linux_benchmark.workloads"
BUILTIN_PLUGIN_ROOT = Path(__file__).resolve().parent / "plugins"


def resolve_user_plugin_dir() -> Path:
    """
    Determine where third-party/user plugins should be installed and loaded from.

    Preference order:
    1) `LB_USER_PLUGIN_DIR` env override (if set).
    2) `<package>/plugins/_user` (portable with runner tree).
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
    except Exception:
        pass
    return candidate


USER_PLUGIN_DIR = resolve_user_plugin_dir()


class PluginRegistry:
    """In-memory registry that supports built-in, entry-point, and user directory plugins."""

    def __init__(self, plugins: Optional[Iterable[Any]] = None):
        self._workloads: Dict[str, IWorkloadPlugin] = {}
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

    def available(self, load_entrypoints: bool = False) -> Dict[str, Any]:
        """
        Return available workload plugins.

        When load_entrypoints is True, pending entry-point plugins are resolved and
        registered; otherwise only already-registered plugins are returned.
        """
        if load_entrypoints:
            self._load_pending_entrypoints()
        return dict(self._workloads)

    def _discover_entrypoint_plugins(self) -> None:
        """Collect entry points without importing them. Loaded on demand."""
        self._pending_entrypoints = discover_entrypoints([ENTRYPOINT_GROUP])

    def _load_pending_entrypoints(self) -> None:
        """Load all pending entry-point plugins."""
        load_pending_entrypoints(
            self._pending_entrypoints, self.register, label="plugin entry point"
        )

    def _load_entrypoint(self, name: str) -> None:
        """Load a single entry-point plugin by name if pending."""
        entry_point = self._pending_entrypoints.pop(name, None)
        if not entry_point:
            return
        load_entrypoint(entry_point, self.register, label="plugin entry point")

    def _load_user_plugins(self) -> None:
        """Load python plugins from user plugin directories."""
        load_plugins_from_dir(resolve_user_plugin_dir(), self.register)
