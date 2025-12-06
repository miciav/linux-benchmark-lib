"""Controller facade for orchestration components.

Re-exports controller-facing types to decouple orchestration from runner
and UI without changing behavior yet.
"""

from linux_benchmark_lib.controller import (
    AnsibleRunnerExecutor,
    BenchmarkController,
    ExecutionResult,
    InventorySpec,
    RunExecutionSummary,
)
from lb_runner.events import LogSink, ProgressEmitter, RunEvent, StdoutEmitter
from linux_benchmark_lib.journal import RunJournal, RunStatus
from linux_benchmark_lib.services.plugin_service import create_registry
from linux_benchmark_lib.services.run_service import RunService
from linux_benchmark_lib.services.setup_service import SetupService

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
    "ProgressEmitter",
    "StdoutEmitter",
    "LogSink",
    "create_registry",
]
