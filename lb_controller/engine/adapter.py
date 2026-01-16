"""Adapter binding services and session for run execution."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from lb_controller.engine.lifecycle import RunLifecycle
from lb_controller.engine.run_state import RunFlags, RunState
from lb_controller.engine.stops import StopCoordinator
from lb_controller.engine.session import RunSession
from lb_controller.models.state import ControllerState, ControllerStateMachine
from lb_controller.models.types import ExecutionResult, InventorySpec, RemoteExecutor, RunExecutionSummary
from lb_controller.services.services import ControllerServices
from lb_runner.api import BenchmarkConfig, RemoteHostConfig, StopToken

logger = logging.getLogger(__name__)


class ControllerAdapter:
    """
    Transient adapter that binds ControllerServices (static) and RunSession (dynamic)
    to provide a unified interface for playbook helpers.
    """

    def __init__(self, services: ControllerServices, session: RunSession) -> None:
        self.services = services
        self.session = session

    @property
    def config(self) -> BenchmarkConfig:
        return self.services.config

    @property
    def executor(self) -> RemoteExecutor:
        return self.services.executor

    @property
    def output_formatter(self) -> Any | None:
        return self.services.output_formatter

    @property
    def stop_token(self) -> StopToken | None:
        return self.services.stop_token

    @property
    def lifecycle(self) -> RunLifecycle:
        return self.services.lifecycle

    @property
    def state_machine(self) -> ControllerStateMachine:
        return self.session.state_machine
    
    @property
    def coordinator(self) -> StopCoordinator | None:
        return self.session.coordinator

    @property
    def _use_progress_stream(self) -> bool:
        return self.services.use_progress_stream
    
    @property
    def _journal_refresh(self) -> Callable[[], None] | None:
        return self.services.journal_refresh

    def _transition(self, state: ControllerState, reason: str | None = None) -> None:
        self.session.transition(state, reason)

    def _stop_requested(self) -> bool:
        if self.stop_token and self.stop_token.should_stop():
            self.session.arm_stop("stop requested")
            return True
        return False

    def _interrupt_executor(self) -> None:
        if hasattr(self.executor, "interrupt"):
            try:
                self.executor.interrupt()
            except Exception:
                pass

    def _refresh_journal(self) -> None:
        if self.services.journal_refresh:
            try:
                self.services.journal_refresh()
            except Exception as exc:
                logger.debug("Journal refresh callback failed: %s", exc)

    def _build_summary(
        self,
        state: RunState,
        phases: Dict[str, ExecutionResult],
        flags: RunFlags,
        success_override: Optional[bool] = None,
    ) -> RunExecutionSummary:
        if self._stop_requested():
            final_state = (
                ControllerState.STOP_FAILED
                if not flags.stop_successful
                else ControllerState.ABORTED
            )
        elif not flags.all_tests_success or success_override is False:
            final_state = ControllerState.FAILED
        else:
            final_state = ControllerState.FINISHED
        self._transition(final_state)
        success = (
            success_override
            if success_override is not None
            else flags.all_tests_success and flags.stop_successful
        )
        return RunExecutionSummary(
            run_id=state.resolved_run_id,
            per_host_output=state.per_host_output,
            phases=phases,
            success=bool(success),
            output_root=state.output_root,
            report_root=state.report_root,
            data_export_root=state.data_export_root,
            controller_state=self.state_machine.state,
            cleanup_allowed=self.state_machine.allows_cleanup(),
        )

    # These methods were part of ControllerContext/Protocol but rely on imported logic.
    # We will need to ensure the imports in the playbook/stop_logic modules don't cycle.
    # For now, we expect the caller to use the helpers directly, but some helpers call back into the controller.
    # So we must expose them here if they are part of the protocol.
    
    def _handle_stop_during_workloads(
        self,
        inventory: InventorySpec,
        extravars: Dict[str, Any],
        flags: RunFlags,
        ui_log: Callable[[str], None],
    ) -> RunFlags:
        from lb_controller.engine.stop_logic import handle_stop_during_workloads
        return handle_stop_during_workloads(self, inventory, extravars, flags, ui_log)  # type: ignore

    def _handle_stop_protocol(
        self,
        inventory: InventorySpec,
        extravars: Dict[str, Any],
        log_fn: Callable[[str], None],
    ) -> bool:
        from lb_controller.engine.stop_logic import handle_stop_protocol
        return handle_stop_protocol(self, inventory, extravars, log_fn) # type: ignore

    def _run_for_hosts(
        self,
        playbook_path: Path,
        base_inventory: InventorySpec,
        hosts: List[RemoteHostConfig],
        extravars: Dict[str, Any],
        tags: List[str] | None = None,
    ) -> ExecutionResult:
        # We can implement this directly using the executor
        limit_hosts = [host.name for host in hosts]
        target_inventory = InventorySpec(
            hosts=hosts,
            inventory_path=base_inventory.inventory_path,
        )
        return self.executor.run_playbook(
            playbook_path,
            inventory=target_inventory,
            extravars=extravars,
            tags=tags,
            limit_hosts=limit_hosts,
        )
