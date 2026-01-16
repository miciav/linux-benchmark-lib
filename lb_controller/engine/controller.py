"""Controller module coordinating remote benchmark execution via Ansible.

This module keeps orchestration logic inside Python while delegating remote
execution to Ansible Runner.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from lb_runner.api import BenchmarkConfig, RunEvent

from lb_controller.models.state import ControllerState, ControllerStateMachine
from lb_controller.services.journal import RunJournal
from lb_controller.adapters.playbooks import run_global_setup
from lb_controller.engine.run_state import RunFlags, RunState
from lb_controller.engine.run_state_builders import (
    ExtravarsBuilder,
    RunDirectoryPreparer,
    build_inventory,
    resolve_run_id,
)
from lb_controller.engine.stops import StopCoordinator
from lb_controller.engine.lifecycle import RunLifecycle, RunPhase
from lb_controller.models.types import ExecutionResult, InventorySpec, RunExecutionSummary
from lb_controller.models.controller_options import ControllerOptions
from lb_controller.services.services import ControllerServices
from lb_controller.engine.session import RunSession
from lb_controller.engine.adapter import ControllerAdapter
from lb_controller.services.teardown_service import TeardownService
from lb_controller.services.ui_notifier import UINotifier
from lb_controller.services.workload_runner import WorkloadRunner

logger = logging.getLogger(__name__)


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
        self._resume_requested = False
        self._current_session: Optional[RunSession] = None

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
        self._resume_requested = resume

        phases: Dict[str, ExecutionResult] = {}
        flags = RunFlags()
        
        session = self._prepare_session(test_types, run_id, journal, journal_path)
        self._current_session = session
        adapter = ControllerAdapter(self.services, session)

        def ui_log(msg: str) -> None:
            self._ui.log(msg)

        ui_log(f"Starting Run {session.run_id}")

        if self.config.remote_execution.run_setup:
            early_summary = run_global_setup(adapter, session.state, phases, flags, ui_log)
            if early_summary:
                return early_summary

        if (
            not adapter._stop_requested()
            and self.state_machine.state != ControllerState.RUNNING_WORKLOADS
        ):
            adapter._transition(ControllerState.RUNNING_WORKLOADS)

        flags = self.workload_runner.run_workloads(
            adapter, session.state, phases, flags, self._resume_requested, ui_log
        )
        self.teardown_service.run_global_teardown(adapter, session.state, phases, flags, ui_log)

        ui_log("Run Finished.")
        time.sleep(1)

        self.lifecycle.finish()
        return adapter._build_summary(session.state, phases, flags)

    def _prepare_session(
        self,
        test_types: List[str],
        run_id: Optional[str],
        journal: Optional[RunJournal],
        journal_path: Optional[Path],
    ) -> RunSession:
        resolved_run_id = resolve_run_id(run_id, journal)
        inventory = build_inventory(self.config)

        coordinator = StopCoordinator(
            expected_runners={h.name for h in self.config.remote_hosts},
            stop_timeout=self._stop_timeout_s,
            run_id=resolved_run_id,
        )
        initial_state = (
            ControllerState.RUNNING_GLOBAL_SETUP
            if self.config.remote_execution.run_setup
            else ControllerState.RUNNING_WORKLOADS
        )
        
        # Determine initial state transition
        # We need to transition the state machine, which is now in the session (or passed to it).
        # But we haven't created the session yet.
        # self.state_machine is injected in __init__. We use that one for now.
        
        self.state_machine.transition(initial_state)
        self.lifecycle.start_phase(
            RunPhase.GLOBAL_SETUP
            if self.config.remote_execution.run_setup
            else RunPhase.WORKLOADS
        )

        target_reps = (
            journal.metadata.get("repetitions") if journal else None
        ) or self.config.repetitions

        output_root, report_root, data_export_root, per_host_output = (
            RunDirectoryPreparer(self.config).prepare(resolved_run_id)
        )

        active_journal = journal or RunJournal.initialize(
            resolved_run_id, self.config, test_types
        )
        journal_file = journal_path or output_root / "run_journal.json"
        active_journal.save(journal_file)
        self._ui.refresh_journal()

        extravars = ExtravarsBuilder(self.config).build(
            run_id=resolved_run_id,
            output_root=output_root,
            report_root=report_root,
            data_export_root=data_export_root,
            per_host_output=per_host_output,
            target_reps=target_reps,
            collector_packages=self._collector_apt_packages(),
        )

        state = RunState(
            resolved_run_id=resolved_run_id,
            inventory=inventory,
            target_reps=target_reps,
            output_root=output_root,
            report_root=report_root,
            data_export_root=data_export_root,
            per_host_output=per_host_output,
            active_journal=active_journal,
            journal_file=journal_file,
            extravars=extravars,
            test_types=list(test_types),
        )
        
        return RunSession(state, coordinator, self.state_machine)

    def _collector_apt_packages(self) -> set[str]:
        # Moved logic from ControllerContext
        packages: set[str] = set()
        if self.config.collectors.cli_commands:
            packages.update({"sysstat", "procps"})
        return packages