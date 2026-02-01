"""ViewModel for Analytics view."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal, QCoreApplication

from lb_app.api import AnalyticsKind
from lb_gui.workers import AnalyticsWorker
from lb_gui.utils import format_datetime

if TYPE_CHECKING:
    from lb_common.api import RunInfo
    from lb_gui.services import AnalyticsServiceWrapper, RunCatalogServiceWrapper, GUIConfigService
    from lb_app.api import BenchmarkConfig


class AnalyticsViewModel(QObject):
    """ViewModel for the Analytics view.

    Manages analytics configuration and execution.
    """

    # Signals
    runs_changed = Signal(list)  # list of RunInfo
    run_selected = Signal(object)  # RunInfo or None
    analytics_started = Signal()
    analytics_completed = Signal(list)  # list of generated artifact paths
    analytics_failed = Signal(str)  # error message
    error_occurred = Signal(str)

    def __init__(
        self,
        analytics_service: "AnalyticsServiceWrapper",
        run_catalog: "RunCatalogServiceWrapper",
        config_service: "GUIConfigService | None" = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._analytics = analytics_service
        self._run_catalog = run_catalog
        self._config_service = config_service

        # State
        self._runs: list["RunInfo"] = []
        self._selected_run: "RunInfo | None" = None
        self._selected_workloads: list[str] = []
        self._selected_hosts: list[str] = []
        self._selected_kind: AnalyticsKind = "aggregate"
        self._last_artifacts: list[Path] = []
        self._worker: AnalyticsWorker | None = None
        self._is_configured: bool = config_service is None

    @property
    def runs(self) -> list["RunInfo"]:
        """Available runs for analysis."""
        return self._runs

    @property
    def selected_run(self) -> "RunInfo | None":
        """Currently selected run."""
        return self._selected_run

    @property
    def available_workloads(self) -> list[str]:
        """Workloads available in the selected run."""
        if self._selected_run is None:
            return []
        return list(self._selected_run.workloads)

    @property
    def available_hosts(self) -> list[str]:
        """Hosts available in the selected run."""
        if self._selected_run is None:
            return []
        return list(self._selected_run.hosts)

    @property
    def selected_workloads(self) -> list[str]:
        """Selected workloads for analysis."""
        return self._selected_workloads

    @selected_workloads.setter
    def selected_workloads(self, value: list[str]) -> None:
        self._selected_workloads = value

    @property
    def selected_hosts(self) -> list[str]:
        """Selected hosts for analysis."""
        return self._selected_hosts

    @selected_hosts.setter
    def selected_hosts(self, value: list[str]) -> None:
        self._selected_hosts = value

    @property
    def selected_kind(self) -> AnalyticsKind:
        """Selected analytics kind."""
        return self._selected_kind

    @selected_kind.setter
    def selected_kind(self, value: AnalyticsKind) -> None:
        self._selected_kind = value

    @property
    def available_kinds(self) -> list[AnalyticsKind]:
        """Available analytics kinds."""
        return self._analytics.get_available_kinds()

    @property
    def last_artifacts(self) -> list[Path]:
        """Artifacts from the last analytics run."""
        return self._last_artifacts

    def refresh_runs(self) -> None:
        """Refresh the list of available runs."""
        if not self._is_configured:
            if not self.configure():
                return
        try:
            self._runs = self._run_catalog.list_runs()
            self._runs.sort(
                key=lambda r: r.created_at or 0,  # type: ignore
                reverse=True,
            )
            self.runs_changed.emit(self._runs)
        except Exception as e:
            self.error_occurred.emit(f"Failed to list runs: {e}")
            self._runs = []
            self.runs_changed.emit([])
            self._is_configured = False

    def configure(self, config_path: Path | None = None) -> bool:
        """Configure the run catalog service using the benchmark config."""
        if self._config_service is None:
            self._is_configured = True
            return True
        if config_path is None:
            cached = None
            try:
                current = self._config_service.get_current_config()
                if isinstance(current, tuple) and len(current) >= 1:
                    cached = current[0]
            except Exception:
                cached = None
            if cached is not None:
                self.configure_with_config(cached)
                return True
        try:
            config, _, _ = self._config_service.load_config(config_path)
            self._run_catalog.configure(config)
            self._is_configured = True
            return True
        except Exception as e:
            self.error_occurred.emit(f"Failed to load config: {e}")
            self._is_configured = False
            return False

    def configure_with_config(self, config: "BenchmarkConfig") -> None:
        """Configure the run catalog service with a preloaded config."""
        self._run_catalog.configure(config)
        self._is_configured = True

    def select_run(self, run_id: str | None) -> None:
        """Select a run for analysis."""
        if run_id is None:
            self._selected_run = None
            self._selected_workloads = []
            self._selected_hosts = []
        else:
            self._selected_run = next(
                (r for r in self._runs if r.run_id == run_id),
                None,
            )
            # Default to all workloads and hosts
            if self._selected_run:
                self._selected_workloads = list(self._selected_run.workloads)
                self._selected_hosts = list(self._selected_run.hosts)

        self.run_selected.emit(self._selected_run)

    def can_run_analytics(self) -> tuple[bool, str]:
        """Check if analytics can be run.

        Returns (can_run, error_message).
        """
        if self._selected_run is None:
            return False, "No run selected"
        if not self._selected_run.output_root:
            return False, "Run has no output directory"
        return True, ""

    def run_analytics(self) -> None:
        """Run analytics on the selected run."""
        can_run, error = self.can_run_analytics()
        if not can_run:
            self.analytics_failed.emit(error)
            return

        if self._selected_run is None:
            return

        if self._worker is not None and self._worker.is_running():
            return

        self.analytics_started.emit()
        self._last_artifacts = []

        if QCoreApplication.instance() is None:
            try:
                artifacts = self._analytics.run_analytics(
                    run_info=self._selected_run,
                    kind=self._selected_kind,
                    workloads=self._selected_workloads or None,
                    hosts=self._selected_hosts or None,
                )
                self._last_artifacts = list(artifacts)
                self.analytics_completed.emit(self._last_artifacts)
            except Exception as exc:
                self.analytics_failed.emit(str(exc))
            return

        self._worker = AnalyticsWorker(
            self._analytics,
            self._selected_run,
            self._selected_kind,
            workloads=self._selected_workloads or None,
            hosts=self._selected_hosts or None,
        )
        self._worker.signals.finished.connect(self._on_worker_finished)
        self._worker.signals.failed.connect(self._on_worker_failed)
        self._worker.start()

    def _on_worker_finished(self, artifacts: list[Path]) -> None:
        """Handle analytics completion from worker."""
        self._last_artifacts = artifacts
        self.analytics_completed.emit(artifacts)
        self._worker = None

    def _on_worker_failed(self, error: str) -> None:
        """Handle analytics failure from worker."""
        self.analytics_failed.emit(error)
        self._worker = None

    def get_run_table_rows(self) -> list[list[str]]:
        """Get runs formatted for table display."""
        rows = []
        for run in self._runs:
            created = format_datetime(run.created_at)
            workloads = ", ".join(run.workloads[:3])
            if len(run.workloads) > 3:
                workloads += f" (+{len(run.workloads) - 3})"
            rows.append([run.run_id, created, workloads])
        return rows
