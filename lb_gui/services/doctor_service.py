"""Wrapper around DoctorService."""

from __future__ import annotations

from typing import TYPE_CHECKING

from lb_app.api import DoctorService, DoctorReport, BenchmarkConfig

if TYPE_CHECKING:
    pass


class DoctorServiceWrapper:
    """Service for running environment health checks."""

    def __init__(self) -> None:
        self._service = DoctorService()

    @property
    def service(self) -> DoctorService:
        """Access the underlying DoctorService."""
        return self._service

    def check_controller(self) -> DoctorReport:
        """Check controller dependencies (Ansible, SSH, etc.)."""
        return self._service.check_controller()

    def check_local_tools(self) -> DoctorReport:
        """Check local tool availability."""
        return self._service.check_local_tools()

    def check_connectivity(self, config: BenchmarkConfig) -> DoctorReport:
        """Check connectivity to configured remote hosts."""
        return self._service.check_connectivity(config)

    def run_all_checks(
        self, config: BenchmarkConfig | None = None
    ) -> list[DoctorReport]:
        """Run all available checks.

        Args:
            config: Optional config for connectivity checks

        Returns:
            List of DoctorReport objects
        """
        reports = [
            self.check_controller(),
            self.check_local_tools(),
        ]
        if config is not None:
            reports.append(self.check_connectivity(config))
        return reports
