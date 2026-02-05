"""Runner registry wrapper combining workload and collector registries."""

from __future__ import annotations

from typing import Any, Dict

from lb_plugins.api import PluginRegistry
from lb_runner.metric_collectors.registry import CollectorRegistry, CollectorPlugin
from lb_runner.models.config import BenchmarkConfig


class RunnerRegistry:
    """Adapter that exposes workload and collector helpers on a single object."""

    def __init__(
        self,
        workloads: PluginRegistry,
        collectors: CollectorRegistry,
    ) -> None:
        self._workloads = workloads
        self._collectors = collectors

    def get(self, name: str) -> Any:
        return self._workloads.get(name)

    def available(self, load_entrypoints: bool = False) -> Dict[str, Any]:
        return self._workloads.available(load_entrypoints=load_entrypoints)

    def create_generator(
        self, plugin_name: str, options: Dict[str, Any] | None = None
    ) -> Any:
        return self._workloads.create_generator(plugin_name, options)

    def create_collectors(self, config: BenchmarkConfig) -> list[Any]:
        return self._collectors.create_collectors(config)

    def available_collectors(
        self, load_entrypoints: bool = False
    ) -> Dict[str, CollectorPlugin]:
        return self._collectors.available(load_entrypoints=load_entrypoints)
