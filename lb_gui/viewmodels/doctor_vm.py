"""ViewModel for Doctor view."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

from lb_gui.workers import DoctorWorker

if TYPE_CHECKING:
    from lb_app.api import DoctorReport, BenchmarkConfig
    from lb_gui.services import DoctorServiceWrapper, GUIConfigService


class DoctorViewModel(QObject):
    """ViewModel for the Doctor view.

    Manages environment health checks.
    """

    # Signals
    checks_started = Signal()
    checks_completed = Signal(list)  # list of DoctorReport
    check_progress = Signal(str)  # current check name
    error_occurred = Signal(str)

    def __init__(
        self,
        doctor_service: "DoctorServiceWrapper",
        config_service: "GUIConfigService",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._doctor = doctor_service
        self._config_service = config_service

        # State
        self._reports: list["DoctorReport"] = []
        self._config: "BenchmarkConfig | None" = None
        self._is_running: bool = False
        self._worker: DoctorWorker | None = None

    @property
    def reports(self) -> list["DoctorReport"]:
        """List of doctor reports."""
        return self._reports

    @property
    def is_running(self) -> bool:
        """Whether checks are currently running."""
        return self._is_running

    @property
    def total_failures(self) -> int:
        """Total failures across all reports."""
        return sum(r.total_failures for r in self._reports)

    @property
    def all_passed(self) -> bool:
        """Whether all checks passed."""
        return self.total_failures == 0 and len(self._reports) > 0

    def load_config(self) -> bool:
        """Load config for connectivity checks.

        Returns True if successful.
        """
        try:
            config, _, _ = self._config_service.load_config()
            self._config = config
            return True
        except Exception:
            self._config = None
            return False

    def run_all_checks(self) -> None:
        """Run all doctor checks."""
        if self._is_running:
            return

        self._is_running = True
        self._reports = []
        self.checks_started.emit()

        self._worker = DoctorWorker(self._doctor, self._config)
        self._worker.signals.progress.connect(self.check_progress.emit)
        self._worker.signals.finished.connect(self._on_worker_finished)
        self._worker.signals.failed.connect(self._on_worker_failed)
        self._worker.start()

    def _on_worker_finished(self, reports: list["DoctorReport"]) -> None:
        """Handle successful completion from worker."""
        self._reports = reports
        self._is_running = False
        self.checks_completed.emit(self._reports)
        self._worker = None

    def _on_worker_failed(self, error: str) -> None:
        """Handle worker failure."""
        self._is_running = False
        self.error_occurred.emit(f"Check failed: {error}")
        self._worker = None

    def get_summary(self) -> dict[str, int]:
        """Get summary counts."""
        total_checks = 0
        passed = 0
        failed = 0

        for report in self._reports:
            for group in report.groups:
                for item in group.items:
                    total_checks += 1
                    if item.ok:
                        passed += 1
                    else:
                        failed += 1

        return {
            "total": total_checks,
            "passed": passed,
            "failed": failed,
        }

    def get_flattened_results(self) -> list[dict[str, str]]:
        """Get results as a flat list for table display."""
        results = []
        for report in self._reports:
            for group in report.groups:
                for item in group.items:
                    results.append({
                        "Group": group.title,
                        "Check": item.label,
                        "Status": "Pass" if item.ok else "FAIL",
                        "Required": "Yes" if item.required else "No",
                    })
        return results

    def get_info_messages(self) -> list[str]:
        """Get all info messages from reports."""
        messages = []
        for report in self._reports:
            messages.extend(report.info_messages)
        return messages
