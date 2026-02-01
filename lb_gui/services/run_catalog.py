"""Wrapper around RunCatalogService."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from lb_app.api import RunCatalogService, BenchmarkConfig

if TYPE_CHECKING:
    from lb_common.api import RunInfo


class RunCatalogServiceWrapper:
    """Service for listing and accessing past runs."""

    def __init__(self) -> None:
        self._service: RunCatalogService | None = None
        self._config: BenchmarkConfig | None = None

    def configure(self, config: BenchmarkConfig) -> None:
        """Configure the service with a benchmark config."""
        self._config = config
        self._service = RunCatalogService(
            config.output_dir,
            report_dir=config.report_dir,
            data_export_dir=config.data_export_dir,
        )

    def _ensure_configured(self) -> RunCatalogService:
        """Ensure service is configured, raise if not."""
        if self._service is None:
            raise RuntimeError(
                "RunCatalogService not configured. Call configure() first."
            )
        return self._service

    def list_runs(self) -> list["RunInfo"]:
        """List all available runs."""
        service = self._ensure_configured()
        return list(service.list_runs())

    def get_run(self, run_id: str) -> "RunInfo | None":
        """Get a specific run by ID."""
        service = self._ensure_configured()
        return service.get_run(run_id)

    def get_results_dir(self) -> Path | None:
        """Get the results directory from config."""
        if self._config is None:
            return None
        return Path(self._config.results_base_dir)
