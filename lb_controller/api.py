"""Public controller API surface."""

from lb_controller.ansible_executor import AnsibleRunnerExecutor
from lb_controller.controller import BenchmarkController
from lb_controller.controller_runner import ControllerRunner
from lb_controller.controller_state import ControllerState, ControllerStateMachine
from lb_controller.contracts import (
    BenchmarkConfig,
    PluginRegistry,
    RemoteExecutionConfig,
    RemoteHostConfig,
    WorkloadConfig,
)
from lb_controller.interrupts import (
    DoubleCtrlCStateMachine,
    RunInterruptState,
    SigintDecision,
    SigintDoublePressHandler,
)
from lb_controller.journal import LogSink, RunJournal, RunStatus, TaskState
from lb_controller.pending import pending_exists
from lb_controller.services import ConfigService, RunCatalogService, RunInfo, create_registry
from lb_controller.services.plugin_service import PluginInstaller, build_plugin_table
from lb_controller.services.setup_service import SetupService
from lb_controller.types import (
    ExecutionResult,
    InventorySpec,
    RemoteExecutor,
    RunExecutionSummary,
)
from lb_runner.events import RunEvent, StdoutEmitter

__all__ = [
    "AnsibleRunnerExecutor",
    "BenchmarkConfig",
    "BenchmarkController",
    "ConfigService",
    "ControllerRunner",
    "ControllerState",
    "ControllerStateMachine",
    "DoubleCtrlCStateMachine",
    "ExecutionResult",
    "InventorySpec",
    "LogSink",
    "pending_exists",
    "PluginInstaller",
    "PluginRegistry",
    "RemoteExecutor",
    "RemoteExecutionConfig",
    "RemoteHostConfig",
    "RunInterruptState",
    "RunCatalogService",
    "RunEvent",
    "RunExecutionSummary",
    "RunInfo",
    "RunJournal",
    "RunStatus",
    "SigintDecision",
    "SetupService",
    "SigintDoublePressHandler",
    "StdoutEmitter",
    "TaskState",
    "WorkloadConfig",
    "build_plugin_table",
    "create_registry",
]
