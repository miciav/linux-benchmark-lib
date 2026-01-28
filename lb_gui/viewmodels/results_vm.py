"""ViewModel for Results view."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

from lb_gui.utils import format_datetime, format_optional

if TYPE_CHECKING:
    from lb_common.api import RunInfo
    from lb_gui.services import RunCatalogServiceWrapper, GUIConfigService
    from lb_app.api import BenchmarkConfig


class ResultsViewModel(QObject):
    """ViewModel for the Results view.

    Manages the list of past runs and selected run details.
    """

    # Signals
    runs_changed = Signal(list)  # list of RunInfo
    selection_changed = Signal(object)  # RunInfo or None
    error_occurred = Signal(str)  # error message

    # Table headers for run list
    RUN_HEADERS = ["Run ID", "Created", "Hosts", "Workloads"]

    def __init__(
        self,
        run_catalog: "RunCatalogServiceWrapper",
        config_service: "GUIConfigService",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._run_catalog = run_catalog
        self._config_service = config_service

        # State
        self._runs: list["RunInfo"] = []
        self._selected_run: "RunInfo | None" = None
        self._is_configured: bool = False

    @property
    def runs(self) -> list["RunInfo"]:
        """List of available runs."""
        return self._runs

    @property
    def selected_run(self) -> "RunInfo | None":
        """Currently selected run."""
        return self._selected_run

    @property
    def is_configured(self) -> bool:
        """Whether the service is configured with a config."""
        return self._is_configured

    def configure(self, config_path: Path | None = None) -> bool:
        """Configure the service with a benchmark config.

        Returns True if successful.
        """
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
        """Configure the service with a preloaded config."""
        self._run_catalog.configure(config)
        self._is_configured = True

    def refresh_runs(self) -> None:
        """Refresh the list of runs."""
        if not self._is_configured:
            self.error_occurred.emit("Service not configured")
            return

        try:
            self._runs = self._run_catalog.list_runs()
            # Sort by created_at descending (newest first)
            self._runs.sort(
                key=lambda r: r.created_at or 0,  # type: ignore
                reverse=True,
            )
            self.runs_changed.emit(self._runs)
        except Exception as e:
            self.error_occurred.emit(f"Failed to list runs: {e}")
            self._runs = []
            self.runs_changed.emit([])

    def select_run(self, run_id: str | None) -> None:
        """Select a run by ID."""
        if run_id is None:
            self._selected_run = None
        else:
            self._selected_run = next(
                (r for r in self._runs if r.run_id == run_id),
                None,
            )
        self.selection_changed.emit(self._selected_run)

    def get_run_table_rows(self) -> list[list[str]]:
        """Get runs formatted as table rows."""
        rows = []
        for run in self._runs:
            created = format_datetime(run.created_at)
            hosts = ", ".join(run.hosts) if run.hosts else "-"
            workloads = ", ".join(run.workloads) if run.workloads else "-"
            rows.append([run.run_id, created, hosts, workloads])
        return rows

    def get_run_details(self, run: "RunInfo | None" = None) -> dict[str, str]:
        """Get details for a run as key-value pairs."""
        run = run or self._selected_run
        if run is None:
            return {}

        details = {
            "Run ID": run.run_id,
            "Output Directory": format_optional(run.output_root),
            "Report Directory": format_optional(run.report_root),
            "Export Directory": format_optional(run.data_export_root),
            "Journal Path": format_optional(run.journal_path),
            "Hosts": ", ".join(run.hosts) if run.hosts else "-",
            "Workloads": ", ".join(run.workloads) if run.workloads else "-",
            "Created": format_datetime(run.created_at),
        }
        return details

    def open_output_directory(self) -> Path | None:
        """Get the output directory path for the selected run."""
        if self._selected_run is None:
            return None
        return self._selected_run.output_root

    def open_report_directory(self) -> Path | None:
        """Get the report directory path for the selected run."""
        if self._selected_run is None:
            return None
        return self._selected_run.report_root
