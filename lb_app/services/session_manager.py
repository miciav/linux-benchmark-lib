"""Session management for benchmark runs."""

from __future__ import annotations

from pathlib import Path
from typing import IO, Any, Callable, Optional

from lb_controller.api import ControllerStateMachine, LogSink, RunJournal, StopToken
from lb_app.ui_interfaces import DashboardHandle, NoOpDashboardHandle, UIAdapter
from lb_app.services.run_journal import (
    build_journal_from_results,
    find_latest_journal,
    generate_run_id,
    initialize_new_journal,
    load_resume_journal,
)
from lb_app.services.run_types import (
    RunContext,
    _RemoteSession,
    _DashboardLogProxy,
)
from lb_app.services.run_plan import build_run_plan


class SessionManager:
    """Manages creation and initialization of run sessions."""

    def __init__(self, registry_factory: Callable[[], Any]):
        self._registry_factory = registry_factory

    def prepare_remote_session(
        self,
        context: RunContext,
        run_id: Optional[str],
        ui_adapter: UIAdapter | None,
        stop_token: StopToken | None,
    ) -> _RemoteSession:
        """Initialize journal, dashboard, log files, and session state."""
        ui_stream_log_file: IO[str] | None = None
        stop = stop_token or StopToken(
            stop_file=context.stop_file, enable_signals=False
        )
        resume_requested = context.resume_from is not None or context.resume_latest
        journal, journal_path, dashboard, effective_run_id = (
            self._prepare_journal_and_dashboard(
                context, run_id, ui_adapter, ui_stream_log_file
            )
        )
        log_path = journal_path.parent / "run.log"
        log_file = log_path.open("a", encoding="utf-8")
        dashboard, ui_stream_log_path, ui_stream_log_file = self._enable_dashboard_log(
            dashboard, journal_path
        )
        sink = LogSink(journal, journal_path, log_path)
        return _RemoteSession(
            journal=journal,
            journal_path=journal_path,
            dashboard=dashboard,
            ui_stream_log_file=ui_stream_log_file,
            ui_stream_log_path=ui_stream_log_path,
            log_path=log_path,
            log_file=log_file,
            sink=sink,
            stop_token=stop,
            effective_run_id=effective_run_id,
            controller_state=ControllerStateMachine(),
            resume_requested=resume_requested,
        )

    def _prepare_journal_and_dashboard(
        self,
        context: RunContext,
        run_id: Optional[str],
        ui_adapter: UIAdapter | None,
        ui_stream_log_file: IO[str] | None = None,
    ) -> tuple[RunJournal, Path, DashboardHandle, str]:
        """Load or create the run journal and optional dashboard."""
        journal, journal_path, run_identifier = self._resolve_journal(context, run_id)
        self._populate_journal_metadata(journal, context)
        self._persist_journal(journal, journal_path)
        self._ensure_stop_file(context, journal_path)
        dashboard = self._create_dashboard(
            context, ui_adapter, journal, ui_stream_log_file
        )
        return journal, journal_path, dashboard, run_identifier

    def _create_dashboard(
        self,
        context: RunContext,
        ui_adapter: UIAdapter | None,
        journal: RunJournal,
        ui_stream_log_file: IO[str] | None,
    ) -> DashboardHandle:
        """Build a dashboard handle or a no-op substitute."""
        if not ui_adapter:
            return NoOpDashboardHandle()

        # We need build_run_plan here.
        # RunService had get_run_plan which delegates to build_run_plan.
        # We can call build_run_plan directly.
        registry = context.registry or self._registry_factory()
        plan = build_run_plan(
            context.config,
            context.target_tests,
            execution_mode=context.execution_mode,
            registry=registry,
        )
        return ui_adapter.create_dashboard(plan, journal, ui_stream_log_file)

    def _enable_dashboard_log(
        self,
        dashboard: DashboardHandle,
        journal_path: Path,
    ) -> tuple[DashboardHandle, Path | None, IO[str] | None]:
        """Attach a ui_stream.log file to the dashboard when available."""
        if isinstance(dashboard, NoOpDashboardHandle):
            return dashboard, None, None
        ui_stream_log_path = journal_path.parent / "ui_stream.log"
        try:
            ui_stream_log_file = ui_stream_log_path.open("a", encoding="utf-8")
        except Exception:
            return dashboard, None, None
        wrapped = _DashboardLogProxy(dashboard, ui_stream_log_file)
        return wrapped, ui_stream_log_path, ui_stream_log_file

    def _resolve_journal(
        self, context: RunContext, run_id: Optional[str]
    ) -> tuple[RunJournal, Path, str]:
        resume_requested = context.resume_from is not None or context.resume_latest
        if resume_requested:
            return load_resume_journal(context, run_id)
        return initialize_new_journal(context, run_id)

    def _populate_journal_metadata(
        self, journal: RunJournal, context: RunContext
    ) -> None:
        if journal.metadata is None:
            return
        journal.metadata.setdefault("execution_mode", context.execution_mode)
        node_count = self._resolve_node_count(context)
        journal.metadata.setdefault("node_count", node_count)

    def _resolve_node_count(self, context: RunContext) -> int:
        node_count = context.node_count
        if node_count is not None:
            return node_count
        host_count = len(context.config.remote_hosts or [])
        if context.execution_mode in ("docker", "multipass"):
            return max(1, host_count)
        return host_count or 1

    def _persist_journal(self, journal: RunJournal, journal_path: Path) -> None:
        # Persist the initial state so resume is possible even if execution aborts early
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        journal.save(journal_path)

    def _ensure_stop_file(self, context: RunContext, journal_path: Path) -> None:
        # Default stop file lives next to the journal.
        if context.stop_file is None:
            context.stop_file = journal_path.parent / "STOP"
