"""Analytics service for running exports on stored runs.

This module wraps `lb_analytics` lazily and is invoked by the UI/controller
layer to produce aggregate artifacts.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Literal, Optional, Sequence

from lb_common.api import RunInfo

logger = logging.getLogger(__name__)

AnalyticsKind = Literal["aggregate"]


@dataclass(frozen=True)
class AnalyticsRequest:
    """Parameters to run analytics on a stored run."""

    run: RunInfo
    kind: AnalyticsKind = "aggregate"
    hosts: Optional[Sequence[str]] = None
    workloads: Optional[Sequence[str]] = None


class AnalyticsService:
    """Execute analytics against existing artifacts."""

    def run(self, request: AnalyticsRequest) -> List[Path]:
        if request.kind == "aggregate":
            return self._run_aggregate(request)
        raise ValueError(f"Unsupported analytics kind: {request.kind}")

    @staticmethod
    def _load_results(results_file: Path) -> Optional[List[dict]]:
        try:
            results = json.loads(results_file.read_text())
        except Exception as exc:
            logger.warning("Failed to parse results %s: %s", results_file, exc)
            return None
        if not isinstance(results, list):
            return None
        return results

    def _process_workload(
        self,
        handler: "DataHandler",
        host_root: Path,
        export_root: Path,
        workload: str,
    ) -> Optional[Path]:
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
        self, handler: "DataHandler", run: RunInfo, host: str, workloads: List[str]
    ) -> List[Path]:
        host_root = run.output_root / host
        if not host_root.exists():
            logger.warning("Host output missing for %s in run %s", host, run.run_id)
            return []

        export_root = host_root / "exports"
        export_root.mkdir(parents=True, exist_ok=True)

        produced: List[Path] = []
        for workload in workloads:
            out_path = self._process_workload(handler, host_root, export_root, workload)
            if out_path:
                produced.append(out_path)
        return produced

    def _run_aggregate(self, request: AnalyticsRequest) -> List[Path]:
        try:
            from lb_analytics.engine.aggregators.data_handler import (  # type: ignore
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

        produced: List[Path] = []
        for host in hosts:
            produced.extend(self._run_aggregate_for_host(handler, run, host, workloads))

        return produced
