"""Wrapper around AnalyticsService."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Sequence

from lb_app.api import AnalyticsService, AnalyticsRequest, AnalyticsKind, RunInfo

if TYPE_CHECKING:
    pass


class AnalyticsServiceWrapper:
    """Service for running analytics on benchmark results."""

    def __init__(self) -> None:
        self._service = AnalyticsService()

    @property
    def service(self) -> AnalyticsService:
        """Access the underlying AnalyticsService."""
        return self._service

    def run_analytics(
        self,
        run_info: RunInfo,
        kind: AnalyticsKind = "aggregate",
        workloads: Sequence[str] | None = None,
        hosts: Sequence[str] | None = None,
    ) -> list[Path]:
        """Run analytics and return generated artifact paths.

        Args:
            run_info: RunInfo object for the run to analyze
            kind: Type of analytics to run (default: "aggregate")
            workloads: Optional filter for specific workloads
            hosts: Optional filter for specific hosts

        Returns:
            List of paths to generated artifacts
        """
        request = AnalyticsRequest(
            run=run_info,
            kind=kind,
            workloads=workloads,
            hosts=hosts,
        )
        return self._service.run(request)

    def get_available_kinds(self) -> list[AnalyticsKind]:
        """Get list of available analytics kinds."""
        return list(AnalyticsKind)
