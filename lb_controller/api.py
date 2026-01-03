"""Public controller API surface.

For threaded start/stop/status helpers, use `lb_controller.async_api`.
"""

from lb_controller.controller import BenchmarkController
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
    SigintDoublePressHandler,
)
from lb_controller.journal import LogSink, RunJournal, RunStatus, TaskState
from lb_controller.pending import pending_exists
from lb_controller.services import ConfigService, RunCatalogService, RunInfo, create_registry
from lb_controller.services.plugin_service import PluginInstaller, build_plugin_table
from lb_controller.types import RunExecutionSummary

__all__ = [
    "BenchmarkConfig",
    "BenchmarkController",
    "ConfigService",
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
