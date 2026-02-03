"""Controller module coordinating remote benchmark execution via Ansible.

This module keeps orchestration logic inside Python while delegating remote
execution to Ansible Runner.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from lb_runner.api import BenchmarkConfig, RunEvent

from lb_controller.engine.stops import StopCoordinator
from lb_controller.models.state import ControllerStateMachine
from lb_controller.services.journal import RunJournal
from lb_controller.engine.lifecycle import RunLifecycle
from lb_controller.engine.session_builder import RunSessionBuilder
from lb_controller.models.types import RunExecutionSummary
from lb_controller.models.controller_options import ControllerOptions
from lb_controller.services.services import ControllerServices
from lb_controller.engine.session import RunSession
from lb_controller.services.run_orchestrator import RunOrchestrator
from lb_controller.services.teardown_service import TeardownService
from lb_controller.services.ui_notifier import UINotifier
from lb_controller.services.workload_runner import WorkloadRunner


class BenchmarkController:
    """Controller coordinating remote benchmark runs."""

    def __init__(
        self,
        config: BenchmarkConfig,
        options: ControllerOptions | None = None,
    ) -> None:
        self.config = config
        from lb_controller.services.paths import apply_playbook_defaults
        from lb_plugins.api import apply_plugin_assets, create_registry
        apply_playbook_defaults(self.config)
        if not self.config.plugin_assets:
            apply_plugin_assets(self.config, create_registry())
        self._options = options or ControllerOptions()
        self.output_formatter = self._options.output_formatter
        self.stop_token = self._options.stop_token
        self._stop_timeout_s = self._options.stop_timeout_s
        self.lifecycle = RunLifecycle()
        self.state_machine = self._options.state_machine or ControllerStateMachine()
        self.executor = self._options.build_executor()
        self._use_progress_stream = True
        self._journal_refresh = self._options.journal_refresh

        self.services = ControllerServices(
            config=self.config,
            executor=self.executor,
            output_formatter=self.output_formatter,
            stop_token=self.stop_token,
            lifecycle=self.lifecycle,
            journal_refresh=self._journal_refresh,
            use_progress_stream=self._use_progress_stream,
        )

        self._ui = UINotifier(
            output_formatter=self.output_formatter,
            journal_refresh=self._journal_refresh,
        )
        self.workload_runner = WorkloadRunner(
            config=self.config,
            ui_notifier=self._ui,
        )
        self.teardown_service = TeardownService()
        self._current_session: Optional[RunSession] = None
        self._session_builder = RunSessionBuilder(
            config=self.config,
            state_machine=self.state_machine,
            stop_timeout_s=self._stop_timeout_s,
            journal_refresh=self._ui.refresh_journal,
            collector_packages=self._collector_apt_packages,
        )
        self._orchestrator = RunOrchestrator(
            services=self.services,
            workload_runner=self.workload_runner,
            teardown_service=self.teardown_service,
            ui_notifier=self._ui,
        )

    def on_event(self, event: RunEvent) -> None:
        """Process an event for stop coordination."""
        if self.coordinator:
            self.coordinator.process_event(event)

    @property
    def coordinator(self) -> StopCoordinator | None:
        return self._current_session.coordinator if self._current_session else None

    def run(
        self,
        test_types: List[str],
        run_id: Optional[str] = None,
        journal: Optional[RunJournal] = None,
        resume: bool = False,
        journal_path: Optional[Path] = None,
    ) -> RunExecutionSummary:
        """
        Execute the configured benchmarks on remote hosts.

        Args:
            test_types: List of benchmark identifiers to execute.
            run_id: Optional run identifier. If not provided, a timestamp-based
                id is generated.
            journal: Optional pre-loaded journal used for resume flows.
            resume: When True, reuse the provided journal instead of creating a new one.
            journal_path: Optional override for where the journal is persisted.
        """
        if not self.config.remote_hosts:
            raise ValueError("At least one remote host must be configured.")
        if resume and journal is None:
            raise ValueError("Resume requested without a journal instance.")

        session = self._session_builder.build(
            test_types=test_types,
            run_id=run_id,
            journal=journal,
            journal_path=journal_path,
        )
        self._current_session = session
        return self._orchestrator.run(session, resume_requested=resume)

    def _collector_apt_packages(self) -> set[str]:
        packages: set[str] = set()
        if self.config.collectors.cli_commands:
            packages.update({"sysstat", "procps"})
        return packages
