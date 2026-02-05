"""Run orchestration service for GUI."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from lb_app.api import BenchmarkConfig, RunJournal, RunRequest
from lb_gui.workers import RunWorker

if TYPE_CHECKING:
    from lb_gui.services.app_client import AppClientService


class RunControllerService:
    """Service for run planning and execution."""

    def __init__(self, app_client: "AppClientService") -> None:
        self._app_client = app_client

    def get_run_plan(
        self,
        config: BenchmarkConfig,
        tests: list[str],
        execution_mode: str = "remote",
    ) -> list[dict[str, Any]]:
        """Get the run plan for the selected tests."""
        return self._app_client.get_run_plan(config, tests, execution_mode)

    def build_journal(self, run_id: str | None) -> RunJournal:
        """Create a minimal run journal for dashboard initialization."""
        return RunJournal(run_id=run_id or "gui-run", tasks={})

    def create_worker(self, request: RunRequest) -> RunWorker:
        """Create a RunWorker for executing the run."""
        return RunWorker(self._app_client, request)
