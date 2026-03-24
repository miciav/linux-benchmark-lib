"""Orchestrates benchmark run execution and dashboard wiring."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lb_app.api import RunRequest
    from lb_gui.services.run_controller import RunControllerService
    from lb_gui.viewmodels.dashboard_vm import GUIDashboardViewModel
    from lb_gui.workers import RunWorker


class RunOrchestrator:
    """Owns the lifecycle of a single benchmark run.

    Encapsulates plan retrieval, adapter creation, dashboard
    initialisation, worker wiring and startup. MainWindow retains only
    UI concerns (navigation, cursor, stop button).
    """

    def __init__(
        self,
        run_controller: "RunControllerService",
        dashboard_vm: "GUIDashboardViewModel",
    ) -> None:
        self._run_ctrl = run_controller
        self._dashboard_vm = dashboard_vm
        self._current_worker: "RunWorker | None" = None

    def is_busy(self) -> bool:
        """Return True if a run is currently active."""
        return (
            self._current_worker is not None
            and self._current_worker.is_running()
        )

    def start_run(self, request: "RunRequest") -> "RunWorker":
        """Prepare and launch a benchmark run.

        Returns the started RunWorker on success.
        Raises RuntimeError if a run is already in progress.
        Raises any exception from get_run_plan on planning failure.
        """
        if self.is_busy():
            raise RuntimeError("A run is already in progress")

        # May raise — let caller handle UI error display
        plan = self._run_ctrl.get_run_plan(
            request.config,
            list(request.tests),
            request.execution_mode,
        )

        from lb_gui.adapters.gui_ui_adapter import GuiUIAdapter

        adapter = GuiUIAdapter(self._dashboard_vm)
        request.ui_adapter = adapter

        journal = self._run_ctrl.build_journal(request.run_id)
        self._dashboard_vm.initialize(plan, journal)

        worker = self._run_ctrl.create_worker(request)
        worker.signals.log_line.connect(self._dashboard_vm.on_log_line)
        worker.signals.status_line.connect(self._dashboard_vm.on_status)
        worker.signals.warning.connect(self._dashboard_vm.on_warning)
        worker.signals.journal_update.connect(self._dashboard_vm.on_journal_update)
        worker.signals.finished.connect(self._on_worker_finished)

        self._current_worker = worker
        worker.start()
        return worker

    def _on_worker_finished(self, _success: bool, _error: str) -> None:
        """Reset internal state when run completes."""
        self._current_worker = None
