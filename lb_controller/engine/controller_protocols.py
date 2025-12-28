"""Protocol definitions to decouple controller helpers from the controller class."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol

from lb_controller.engine.lifecycle import RunLifecycle
from lb_controller.engine.run_state import RunFlags, RunState
from lb_controller.engine.stops import StopCoordinator
from lb_controller.models.state import ControllerState, ControllerStateMachine
from lb_controller.models.types import ExecutionResult, InventorySpec, RemoteExecutor, RunExecutionSummary
from lb_runner.api import BenchmarkConfig, RemoteHostConfig, StopToken


class ControllerProtocol(Protocol):
    config: BenchmarkConfig
    executor: RemoteExecutor
    output_formatter: Any | None
    stop_token: StopToken | None
    lifecycle: RunLifecycle
    state_machine: ControllerStateMachine
    coordinator: StopCoordinator | None
    _use_progress_stream: bool
    _journal_refresh: Callable[[], None] | None

    def _stop_requested(self) -> bool: ...

    def _transition(self, state: ControllerState, reason: str | None = None) -> None: ...

    def _interrupt_executor(self) -> None: ...

    def _refresh_journal(self) -> None: ...

    def _build_summary(
        self,
        state: RunState,
        phases: Dict[str, ExecutionResult],
        flags: RunFlags,
        success_override: Optional[bool] = None,
    ) -> RunExecutionSummary: ...

    def _handle_stop_during_workloads(
        self,
        inventory: InventorySpec,
        extravars: Dict[str, Any],
        flags: RunFlags,
        ui_log: Callable[[str], None],
    ) -> RunFlags: ...

    def _run_for_hosts(
        self,
        playbook_path: Path,
        base_inventory: InventorySpec,
        hosts: List[RemoteHostConfig],
        extravars: Dict[str, Any],
        tags: List[str] | None = None,
    ) -> ExecutionResult: ...
