"""Registry for metric collector plugins."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Optional

from lb_common.entrypoints import discover_entrypoints, load_pending_entrypoints
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
        self._pending_entrypoints: Dict[str, Any] = {}
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
        self._pending_entrypoints = discover_entrypoints([ENTRYPOINT_GROUP])

    def _load_pending_entrypoints(self) -> None:
        """Load all pending entry-point plugins."""
        load_pending_entrypoints(
            self._pending_entrypoints, self.register, label="collector entry point"
        )
