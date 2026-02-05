"""Orchestrate controller run phases."""

from __future__ import annotations

import time
from typing import Callable, Dict

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

        ui_log = self._make_ui_log()
        self._enter_initial_state(session)
        ui_log(f"Starting Run {session.run_id}")

        early_summary = self._maybe_run_setup(session, phases, flags, ui_log)
        if early_summary:
            return early_summary

        stop_requested = self._maybe_arm_stop(session)
        self._ensure_running_workloads(session, stop_requested)

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

        self._finalize_run(ui_log)
        return build_summary(self._services, session, phases, flags)

    def _make_ui_log(self) -> Callable[[str], None]:
        def ui_log(msg: str) -> None:
            self._ui.log(msg)

        return ui_log

    def _enter_initial_state(self, session: RunSession) -> None:
        if self._services.config.remote_execution.run_setup:
            session.transition(ControllerState.RUNNING_GLOBAL_SETUP)
            self._services.lifecycle.start_phase(RunPhase.GLOBAL_SETUP)
            return
        session.transition(ControllerState.RUNNING_WORKLOADS)
        self._services.lifecycle.start_phase(RunPhase.WORKLOADS)

    def _maybe_run_setup(
        self,
        session: RunSession,
        phases: Dict[str, ExecutionResult],
        flags: RunFlags,
        ui_log: Callable[[str], None],
    ) -> RunExecutionSummary | None:
        if not self._services.config.remote_execution.run_setup:
            return None
        return run_global_setup(self._services, session, phases, flags, ui_log)

    def _maybe_arm_stop(self, session: RunSession) -> bool:
        stop_requested = (
            self._services.stop_token and self._services.stop_token.should_stop()
        )
        if stop_requested:
            session.arm_stop("stop requested")
        return bool(stop_requested)

    @staticmethod
    def _ensure_running_workloads(session: RunSession, stop_requested: bool) -> None:
        if stop_requested:
            return
        if session.state_machine.state != ControllerState.RUNNING_WORKLOADS:
            session.transition(ControllerState.RUNNING_WORKLOADS)

    def _finalize_run(self, ui_log: Callable[[str], None]) -> None:
        ui_log("Run Finished.")
        time.sleep(1)
        self._services.lifecycle.finish()
