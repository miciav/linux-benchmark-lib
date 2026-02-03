"""Orchestrate controller run phases."""

from __future__ import annotations

import time
from typing import Dict

from lb_controller.adapters.playbooks import build_summary, run_global_setup
from lb_controller.engine.lifecycle import RunPhase
from lb_controller.engine.run_state import RunFlags
from lb_controller.engine.session import RunSession
from lb_controller.models.state import ControllerState
from lb_controller.models.types import ExecutionResult, RunExecutionSummary
from lb_controller.services.services import ControllerServices
from lb_controller.services.teardown_service import TeardownService
from lb_controller.services.ui_notifier import UINotifier
from lb_controller.services.workload_runner import WorkloadRunner


class RunOrchestrator:
    """Coordinate controller phases for a run."""

    def __init__(
        self,
        *,
        services: ControllerServices,
        workload_runner: WorkloadRunner,
        teardown_service: TeardownService,
        ui_notifier: UINotifier,
    ) -> None:
        self._services = services
        self._workload_runner = workload_runner
        self._teardown_service = teardown_service
        self._ui = ui_notifier

    def run(
        self,
        session: RunSession,
        *,
        resume_requested: bool,
    ) -> RunExecutionSummary:
        phases: Dict[str, ExecutionResult] = {}
        flags = RunFlags()

        initial_state = (
            ControllerState.RUNNING_GLOBAL_SETUP
            if self._services.config.remote_execution.run_setup
            else ControllerState.RUNNING_WORKLOADS
        )
        session.transition(initial_state)
        self._services.lifecycle.start_phase(
            RunPhase.GLOBAL_SETUP
            if self._services.config.remote_execution.run_setup
            else RunPhase.WORKLOADS
        )

        def ui_log(msg: str) -> None:
            self._ui.log(msg)

        ui_log(f"Starting Run {session.run_id}")

        if self._services.config.remote_execution.run_setup:
            early_summary = run_global_setup(
                self._services, session, phases, flags, ui_log
            )
            if early_summary:
                return early_summary

        stop_requested = (
            self._services.stop_token and self._services.stop_token.should_stop()
        )
        if stop_requested:
            session.arm_stop("stop requested")

        if (
            not stop_requested
            and session.state_machine.state != ControllerState.RUNNING_WORKLOADS
        ):
            session.transition(ControllerState.RUNNING_WORKLOADS)

        flags = self._workload_runner.run_workloads(
            self._services,
            session,
            session.state,
            phases,
            flags,
            resume_requested,
            ui_log,
        )
        self._teardown_service.run_global_teardown(
            self._services, session, session.state, phases, flags, ui_log
        )

        ui_log("Run Finished.")
        time.sleep(1)

        self._services.lifecycle.finish()
        return build_summary(self._services, session, phases, flags)
