"""Controller facade for orchestration components.

Re-exports controller-facing types to decouple orchestration from runner
and UI without changing behavior yet.
"""

from lb_controller.ansible_executor import AnsibleRunnerExecutor
from lb_controller.controller import BenchmarkController
from lb_controller.journal import LogSink, RunJournal, RunStatus
from lb_controller.services.plugin_service import create_registry
from lb_controller.services.run_service import RunService
from lb_controller.services.setup_service import SetupService
from lb_controller.types import ExecutionResult, InventorySpec, RunExecutionSummary
from lb_runner.events import RunEvent, StdoutEmitter

__all__ = [
    "AnsibleRunnerExecutor",
    "BenchmarkController",
    "ExecutionResult",
    "InventorySpec",
    "RunExecutionSummary",
    "RunJournal",
    "RunService",
    "RunStatus",
    "SetupService",
    "RunEvent",
    "StdoutEmitter",
    "LogSink",
    "create_registry",
]
