"""ViewModel for Dashboard view - wraps lb_app.api dashboard types."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, Signal

from lb_app.api import (
    DashboardViewModel as AppDashboardViewModel,
    DashboardSnapshot,
    DashboardStatusSummary,
    build_dashboard_viewmodel,
    RunJournal,
)

if TYPE_CHECKING:
    pass


class GUIDashboardViewModel(QObject):
    """Qt-aware wrapper around lb_app.api.DashboardViewModel.

    Manages dashboard state and emits signals for UI updates.
    """

    # Signals
    snapshot_changed = Signal(object)  # DashboardSnapshot
    log_line_received = Signal(str)
    status_changed = Signal(str)
    warning_received = Signal(str, float)  # message, ttl
    run_finished = Signal(bool, str)  # success, error_message

    # Table column headers
    JOURNAL_HEADERS = [
        "Host",
        "Workload",
        "Intensity",
        "Status",
        "Progress",
        "Current Action",
        "Last Rep Time",
    ]

    PLAN_HEADERS = ["Workload", "Config"]

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._app_vm: AppDashboardViewModel | None = None
        self._snapshot: DashboardSnapshot | None = None
        self._log_lines: list[str] = []
        self._is_running: bool = False
        self._current_status: str = ""

    @property
    def is_running(self) -> bool:
        """Whether a run is currently active."""
        return self._is_running

    @property
    def snapshot(self) -> DashboardSnapshot | None:
        """Current dashboard snapshot."""
        return self._snapshot

    @property
    def log_lines(self) -> list[str]:
        """Accumulated log lines."""
        return self._log_lines

    @property
    def current_status(self) -> str:
        """Current controller status."""
        return self._current_status

    def initialize(self, plan: list[dict[str, Any]], journal: RunJournal) -> None:
        """Initialize the dashboard with a plan and journal.

        Called when a run starts.
        """
        self._app_vm = build_dashboard_viewmodel(plan, journal)
        self._log_lines = []
        self._is_running = True
        self._current_status = "Initializing..."
        self.refresh_snapshot()

    def refresh_snapshot(self) -> None:
        """Refresh the snapshot from the underlying viewmodel."""
        if self._app_vm is None:
            return
        self._snapshot = self._app_vm.snapshot()
        self.snapshot_changed.emit(self._snapshot)

    def clear(self) -> None:
        """Clear the dashboard state."""
        self._app_vm = None
        self._snapshot = None
        self._log_lines = []
        self._is_running = False
        self._current_status = ""

    # Methods called by RunWorker signal handlers

    def on_log_line(self, line: str) -> None:
        """Handle incoming log line."""
        self._log_lines.append(line)
        self.log_line_received.emit(line)

    def on_status(self, status: str) -> None:
        """Handle status update."""
        self._current_status = status
        self.status_changed.emit(status)

    def on_warning(self, message: str, ttl: float) -> None:
        """Handle warning."""
        self.warning_received.emit(message, ttl)

    def on_journal_update(self, journal: RunJournal) -> None:
        """Handle journal update - refresh snapshot."""
        if self._app_vm is not None:
            # The app viewmodel holds a reference to the journal,
            # so we just need to refresh the snapshot
            self.refresh_snapshot()

    def on_run_finished(self, success: bool, error: str) -> None:
        """Handle run completion."""
        self._is_running = False
        self._current_status = "Completed" if success else f"Failed: {error}"
        self.run_finished.emit(success, error)

    # Data access methods for views

    def get_journal_rows(self) -> list[list[str]]:
        """Get journal data as table rows."""
        if self._snapshot is None:
            return []
        return [
            [
                row.host,
                row.workload,
                row.intensity,
                row.status,
                row.progress,
                row.current_action,
                row.last_rep_time,
            ]
            for row in self._snapshot.rows
        ]

    def get_plan_rows(self) -> list[list[str]]:
        """Get plan data as table rows."""
        if self._snapshot is None:
            return []
        return self._snapshot.plan_rows

    def get_status_summary(self) -> DashboardStatusSummary | None:
        """Get the status summary."""
        if self._snapshot is None:
            return None
        return self._snapshot.status_summary

    def get_run_id(self) -> str:
        """Get the current run ID."""
        if self._snapshot is None:
            return ""
        return self._snapshot.run_id
