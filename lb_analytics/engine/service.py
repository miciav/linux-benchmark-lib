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

from lb_controller.api import RunInfo

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

    def _run_aggregate(self, request: AnalyticsRequest) -> List[Path]:
        try:
            from lb_analytics.engine.aggregators.data_handler import DataHandler  # type: ignore
        except Exception as exc:
            raise RuntimeError(
                "lb_analytics is required for analytics. Install with the controller extra."
            ) from exc

        produced: List[Path] = []
        run = request.run
        hosts = list(request.hosts or run.hosts)
        workloads = list(request.workloads or run.workloads)

        for host in hosts:
            host_root = run.output_root / host
            if not host_root.exists():
                logger.warning("Host output missing for %s in run %s", host, run.run_id)
                continue
            export_root = host_root / "exports"
            export_root.mkdir(parents=True, exist_ok=True)

            for workload in workloads:
                results_file = host_root / workload / f"{workload}_results.json"
                if not results_file.exists():
                    continue
                try:
                    results = json.loads(results_file.read_text())
                except Exception as exc:
                    logger.warning("Failed to parse results %s: %s", results_file, exc)
                    continue
                if not isinstance(results, list):
                    continue

                handler = DataHandler()
                df = handler.process_test_results(workload, results)
                if df is None:
                    continue
                out_path = export_root / f"{workload}_aggregated.csv"
                df.to_csv(out_path)
                produced.append(out_path)

        return produced
