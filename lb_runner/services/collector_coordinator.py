"""Coordinator for collector lifecycle steps."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from lb_common.errors import MetricCollectionError, error_to_payload
from lb_runner.services.results import collect_metrics


class CollectorCoordinator:
    """Manage collector creation, start/stop, and metric harvesting."""

    def __init__(self, registry: Any) -> None:
        self._registry = registry

    def create_collectors(self, config: Any) -> list[Any]:
        return self._registry.create_collectors(config)

    def start(self, collectors: list[Any], logger: logging.Logger) -> None:
        errors: list[MetricCollectionError] = []
        for collector in collectors:
            try:
                collector.start()
            except Exception as exc:
                error = MetricCollectionError(
                    "Collector start failed",
                    context={"collector": getattr(collector, "name", "unknown")},
                    cause=exc,
                )
                errors.append(error)
                logger.exception(
                    "Failed to start collector %s", getattr(collector, "name", "unknown")
                )
        if errors:
            raise MetricCollectionError(
                "One or more collectors failed to start",
                context={"errors": [error_to_payload(err) for err in errors]},
            )

    def stop(self, collectors: list[Any], logger: logging.Logger) -> None:
        for collector in collectors:
            try:
                collector.stop()
            except Exception as exc:
                logger.exception(
                    "Failed to stop collector %s", getattr(collector, "name", "unknown")
                )

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
