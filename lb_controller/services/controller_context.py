"""Controller runtime context used by orchestration helpers."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from lb_controller.adapters.playbooks import run_for_hosts
from lb_controller.engine.stop_logic import (
    handle_stop_during_workloads,
    handle_stop_protocol,
)
from lb_controller.engine.run_state import RunFlags, RunState
from lb_controller.engine.stops import StopCoordinator
from lb_controller.engine.lifecycle import RunLifecycle
from lb_controller.models.state import ControllerState, ControllerStateMachine
from lb_controller.models.types import (
    ExecutionResult,
    InventorySpec,
    RemoteExecutor,
    RunExecutionSummary,
)
from lb_runner.api import BenchmarkConfig, RemoteHostConfig, StopToken

logger = logging.getLogger(__name__)


class ControllerContext:
    """Runtime context implementing controller protocol for adapters."""

    def __init__(
        self,
        config: BenchmarkConfig,
        executor: RemoteExecutor,
        *,
        output_formatter: Any | None = None,
        stop_token: StopToken | None = None,
        lifecycle: RunLifecycle | None = None,
        state_machine: ControllerStateMachine | None = None,
        journal_refresh: Callable[[], None] | None = None,
        use_progress_stream: bool = True,
    ) -> None:
        self.config = config
        self.executor = executor
        self.output_formatter = output_formatter
        self.stop_token = stop_token
        self.lifecycle = lifecycle or RunLifecycle()
        self.state_machine = state_machine or ControllerStateMachine()
        self.coordinator: StopCoordinator | None = None
        self._journal_refresh = journal_refresh
        self._use_progress_stream = use_progress_stream

    def _transition(self, state: ControllerState, reason: str | None = None) -> None:
        try:
            self.state_machine.transition(state, reason=reason)
        except ValueError:
            logger.debug(
                "Invalid transition ignored: %s -> %s",
                self.state_machine.state,
                state,
            )

    def _arm_stop(self, reason: str | None = None) -> None:
        try:
            self.state_machine.transition(ControllerState.STOP_ARMED, reason=reason)
        except Exception:
            pass

    def _stop_requested(self) -> bool:
        if self.stop_token and self.stop_token.should_stop():
            self._arm_stop("stop requested")
            return True
        return False

    def _interrupt_executor(self) -> None:
        exec_obj = self.executor
        if hasattr(exec_obj, "interrupt"):
            try:
                exec_obj.interrupt()  # type: ignore[attr-defined]
            except Exception:
                pass

    def _refresh_journal(self) -> None:
        if not self._journal_refresh:
            return
        try:
            self._journal_refresh()
        except Exception as exc:  # pragma: no cover - defensive
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

    def _handle_stop_during_workloads(
        self,
        inventory: InventorySpec,
        extravars: Dict[str, Any],
        flags: RunFlags,
        ui_log: Callable[[str], None],
    ) -> RunFlags:
        return handle_stop_during_workloads(self, inventory, extravars, flags, ui_log)

    def _handle_stop_protocol(
        self,
        inventory: InventorySpec,
        extravars: Dict[str, Any],
        log_fn: Callable[[str], None],
    ) -> bool:
        return handle_stop_protocol(self, inventory, extravars, log_fn)

    def _run_for_hosts(
        self,
        playbook_path: Path,
        base_inventory: InventorySpec,
        hosts: List[RemoteHostConfig],
        extravars: Dict[str, Any],
        tags: List[str] | None = None,
    ) -> ExecutionResult:
        return run_for_hosts(
            self,
            playbook_path,
            base_inventory,
            hosts,
            extravars,
            tags,
        )

    def _collector_apt_packages(self) -> Set[str]:
        packages: Set[str] = set()
        if self.config.collectors.cli_commands:
            packages.update({"sysstat", "procps"})
        return packages
