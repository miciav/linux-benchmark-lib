"""
Metric management for benchmark execution.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from typing import Any, Dict, Optional
from pathlib import Path

from lb_runner.services.collector_coordinator import CollectorCoordinator
from lb_runner.services.log_handler import LBEventLogHandler
from lb_runner.services import system_info
from lb_runner.services.runner_output_manager import RunnerOutputManager

logger = logging.getLogger(__name__)


class MetricManager:
    """Manages system info, event logging, and metric collectors."""

    def __init__(
        self,
        registry: Any,
        output_manager: RunnerOutputManager,
        host_name: str,
    ):
        self._coordinator = CollectorCoordinator(registry)
        self._output_manager = output_manager
        self._host_name = host_name
        self.system_info: Optional[Dict[str, Any]] = None

    def collect_system_info(self) -> Dict[str, Any]:
        """Collect and persist system information."""
        logger.info("Collecting system information")
        collected = system_info.collect_system_info()
        self.system_info = collected.to_dict()
        self._output_manager.write_system_info(collected)
        return self.system_info

    def create_collectors(self, config: Any) -> list[Any]:
        """Create new collector instances for a run."""
        return self._coordinator.create_collectors(config)

    def start_collectors(self, collectors: list[Any]) -> None:
        """Start all collectors."""
        self._coordinator.start(collectors, logger)

    def stop_collectors(self, collectors: list[Any]) -> None:
        """Stop all collectors."""
        self._coordinator.stop(collectors, logger)

    def collect_metrics(
        self,
        collectors: list[Any],
        workload_dir: Path,
        rep_dir: Path,
        test_name: str,
        repetition: int,
        result: dict[str, Any],
    ) -> None:
        """Harvest metrics from collectors and attach to result."""
        self._coordinator.collect(
            collectors, workload_dir, rep_dir, test_name, repetition, result
        )

    def attach_event_logger(
        self,
        test_name: str,
        repetition: int,
        total_repetitions: int,
        current_run_id: str | None,
    ) -> logging.Handler | None:
        """Attach the LBEventLogHandler for the current test."""
        raw = os.environ.get("LB_ENABLE_EVENT_LOGGING", "1").strip().lower()
        if raw in {"0", "false", "no"}:
            return None
        handler = LBEventLogHandler(
            run_id=current_run_id or "",
            host=self._host_name,
            workload=test_name,
            repetition=repetition,
            total_repetitions=total_repetitions,
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logging.getLogger().addHandler(handler)
        return handler

    def begin_repetition(
        self,
        config: Any,
        *,
        test_name: str,
        repetition: int,
        total_repetitions: int,
        current_run_id: str | None,
    ) -> "MetricSession":
        """Create a MetricSession for a repetition lifecycle."""
        collectors = self.create_collectors(config)
        log_handler = self.attach_event_logger(
            test_name=test_name,
            repetition=repetition,
            total_repetitions=total_repetitions,
            current_run_id=current_run_id,
        )
        return MetricSession(
            metric_manager=self,
            collectors=collectors,
            log_handler=log_handler,
        )

    @staticmethod
    def detach_event_logger(handler: logging.Handler | None) -> None:
        """Remove the event logger handler."""
        if handler:
            logging.getLogger().removeHandler(handler)


@dataclass
class MetricSession:
    """Lifecycle wrapper for repetition collectors and event logging."""

    metric_manager: MetricManager
    collectors: list[Any]
    log_handler: logging.Handler | None

    def start(self) -> None:
        self.metric_manager.start_collectors(self.collectors)

    def stop(self) -> None:
        self.metric_manager.stop_collectors(self.collectors)

    def collect(
        self,
        workload_dir: Path,
        rep_dir: Path,
        test_name: str,
        repetition: int,
        result: dict[str, Any],
    ) -> None:
        self.metric_manager.collect_metrics(
            self.collectors, workload_dir, rep_dir, test_name, repetition, result
        )

    def close(self) -> None:
        self.metric_manager.detach_event_logger(self.log_handler)
