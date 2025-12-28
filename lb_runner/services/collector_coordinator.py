"""Coordinator for collector lifecycle steps."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from lb_runner.services.results import collect_metrics


class CollectorCoordinator:
    """Manage collector creation, start/stop, and metric harvesting."""

    def __init__(self, registry: Any) -> None:
        self._registry = registry

    def create_collectors(self, config: Any) -> list[Any]:
        return self._registry.create_collectors(config)

    def start(self, collectors: list[Any], logger: logging.Logger) -> None:
        for collector in collectors:
            try:
                collector.start()
            except Exception as exc:
                logger.error("Failed to start collector %s: %s", collector.name, exc)

    def stop(self, collectors: list[Any], logger: logging.Logger) -> None:
        for collector in collectors:
            try:
                collector.stop()
            except Exception as exc:
                logger.error("Failed to stop collector %s: %s", collector.name, exc)

    def collect(
        self,
        collectors: list[Any],
        workload_dir: Path,
        rep_dir: Path,
        test_name: str,
        repetition: int,
        result: dict[str, Any],
    ) -> None:
        collect_metrics(collectors, workload_dir, rep_dir, test_name, repetition, result)
