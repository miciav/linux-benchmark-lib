"""Analytics service for running exports on stored runs.

This module wraps `lb_analytics` lazily and is invoked by the UI/controller
layer to produce aggregate artifacts.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from lb_common.api import RunInfo

logger = logging.getLogger(__name__)

AnalyticsKind = Literal["aggregate"]

if TYPE_CHECKING:
    from lb_analytics.engine.aggregators.data_handler import DataHandler, TestResult


@dataclass(frozen=True)
class AnalyticsRequest:
    """Parameters to run analytics on a stored run."""

    run: RunInfo
    kind: AnalyticsKind = "aggregate"
    hosts: Sequence[str] | None = None
    workloads: Sequence[str] | None = None


class AnalyticsService:
    """Execute analytics against existing artifacts."""

    def run(self, request: AnalyticsRequest) -> list[Path]:
        if request.kind == "aggregate":
            return self._run_aggregate(request)
        raise ValueError(f"Unsupported analytics kind: {request.kind}")

    def _load_results(self, results_file: Path) -> list[TestResult] | None:
        try:
            results = json.loads(results_file.read_text())
        except Exception as exc:
            logger.warning("Failed to parse results %s: %s", results_file, exc)
            return None
        if not isinstance(results, list):
            return None
        return self._coerce_test_results(results)

    @staticmethod
    def _coerce_test_results(results: list[Any]) -> list[TestResult] | None:
        if not all(isinstance(item, dict) for item in results):
            return None
        return cast(list["TestResult"], results)

    def _process_workload(
        self,
        handler: DataHandler,
        host_root: Path,
        export_root: Path,
        workload: str,
    ) -> Path | None:
        results_file = host_root / workload / f"{workload}_results.json"
        if not results_file.exists():
            return None
        results = self._load_results(results_file)
        if results is None:
            return None
        df = handler.process_test_results(workload, results)
        if df is None:
            return None
        out_path = export_root / f"{workload}_aggregated.csv"
        df.to_csv(out_path)
        return out_path

    def _run_aggregate_for_host(
        self, handler: DataHandler, run: RunInfo, host: str, workloads: list[str]
    ) -> list[Path]:
        host_root = run.output_root / host
        if not host_root.exists():
            logger.warning("Host output missing for %s in run %s", host, run.run_id)
            return []

        export_root = host_root / "exports"
        export_root.mkdir(parents=True, exist_ok=True)

        produced: list[Path] = []
        for workload in workloads:
            out_path = self._process_workload(handler, host_root, export_root, workload)
            if out_path:
                produced.append(out_path)
        return produced

    def _run_aggregate(self, request: AnalyticsRequest) -> list[Path]:
        try:
            from lb_analytics.engine.aggregators.data_handler import (
                DataHandler,
            )
        except Exception as exc:
            raise RuntimeError(
                "lb_analytics is required for analytics. "
                "Install with the controller extra."
            ) from exc

        run = request.run
        hosts = list(request.hosts or run.hosts)
        workloads = list(request.workloads or run.workloads)
        handler = DataHandler()

        produced: list[Path] = []
        for host in hosts:
            produced.extend(self._run_aggregate_for_host(handler, run, host, workloads))

        return produced
