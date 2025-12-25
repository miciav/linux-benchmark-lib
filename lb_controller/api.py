"""Public controller API surface."""

from lb_controller.engine.controller import BenchmarkController
from lb_controller.adapters.remote_runner import ControllerRunner
from lb_controller.models.state import ControllerState, ControllerStateMachine
from lb_controller.models.contracts import (
    BenchmarkConfig,
    PluginRegistry,
    RemoteExecutionConfig,
    RemoteHostConfig,
    WorkloadConfig,
)
from lb_controller.engine.interrupts import (
    DoubleCtrlCStateMachine,
    SigintDoublePressHandler,
)
from lb_controller.services.journal import LogSink, RunJournal, RunStatus, TaskState
from lb_controller.models.pending import pending_exists
from lb_controller.services import ConfigService, RunCatalogService, RunInfo, create_registry
from lb_controller.services.plugin_service import PluginInstaller, build_plugin_table
from lb_controller.models.types import RunExecutionSummary

__all__ = [
    "BenchmarkConfig",
    "BenchmarkController",
    "ConfigService",
    "ControllerRunner",
    "ControllerState",
    "ControllerStateMachine",
    "DoubleCtrlCStateMachine",
    "LogSink",
    "pending_exists",
    "PluginInstaller",
    "PluginRegistry",
    "RemoteExecutionConfig",
    "RemoteHostConfig",
    "RunCatalogService",
    "RunExecutionSummary",
    "RunInfo",
    "RunJournal",
    "RunStatus",
    "SigintDoublePressHandler",
    "TaskState",
    "WorkloadConfig",
    "build_plugin_table",
    "create_registry",
]
