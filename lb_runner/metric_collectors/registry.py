"""Registry for metric collector plugins."""

from __future__ import annotations

import importlib.metadata
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Optional

from lb_runner.metric_collectors._base_collector import BaseCollector
from lb_runner.models.config import BenchmarkConfig

logger = logging.getLogger(__name__)

ENTRYPOINT_GROUP = "linux_benchmark.collectors"


@dataclass
class CollectorPlugin:
    """Metadata and factory for a metric collector plugin."""

    name: str
    description: str
    factory: Callable[[BenchmarkConfig], BaseCollector]
    aggregator: Optional[Callable[[Any], Dict[str, float]]] = None
    should_run: Callable[[BenchmarkConfig], bool] = lambda _: True


class CollectorRegistry:
    """Registry for collector plugins (built-in + entry points)."""

    def __init__(self, plugins: Optional[Iterable[Any]] = None) -> None:
        self._collectors: Dict[str, CollectorPlugin] = {}
        self._pending_entrypoints: Dict[str, importlib.metadata.EntryPoint] = {}
        if plugins:
            for plugin in plugins:
                self.register(plugin)
        self._discover_entrypoint_plugins()

    def register(self, plugin: Any) -> None:
        """Register a collector plugin."""
        if isinstance(plugin, CollectorPlugin):
            self._collectors[plugin.name] = plugin
            return
        if hasattr(plugin, "name") and hasattr(plugin, "factory"):
            self._collectors[plugin.name] = plugin
            return
        raise TypeError(f"Unknown collector plugin type: {type(plugin)}")

    def available(self, load_entrypoints: bool = False) -> Dict[str, CollectorPlugin]:
        """Return available collector plugins."""
        if load_entrypoints:
            self._load_pending_entrypoints()
        return dict(self._collectors)

    def create_collectors(self, config: BenchmarkConfig) -> list[BaseCollector]:
        self._load_pending_entrypoints()
        collectors: list[BaseCollector] = []
        for plugin in self._collectors.values():
            if plugin.should_run(config):
                try:
                    collector = plugin.factory(config)
                    collectors.append(collector)
                except Exception as exc:
                    logger.error("Failed to create collector %s: %s", plugin.name, exc)
        return collectors

    def _discover_entrypoint_plugins(self) -> None:
        """Collect entry points without importing them. Loaded on demand."""
        try:
            eps = importlib.metadata.entry_points().select(group=ENTRYPOINT_GROUP)
        except Exception:
            eps = []
        for entry_point in eps:
            self._pending_entrypoints.setdefault(entry_point.name, entry_point)

    def _load_pending_entrypoints(self) -> None:
        """Load all pending entry-point plugins."""
        for name in list(self._pending_entrypoints.keys()):
            entry_point = self._pending_entrypoints.pop(name, None)
            if not entry_point:
                continue
            try:
                plugin = entry_point.load()
                self.register(plugin)
            except ImportError as exc:
                logger.debug(
                    "Skipping collector entry point %s due to missing dependency: %s",
                    entry_point.name,
                    exc,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to load collector entry point %s: %s",
                    entry_point.name,
                    exc,
                )
