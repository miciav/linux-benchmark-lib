"""Configuration options for BenchmarkController construction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from lb_controller.adapters.ansible_runner import AnsibleRunnerExecutor
from lb_controller.models.state import ControllerStateMachine
from lb_controller.models.types import RemoteExecutor
from lb_runner.api import StopToken


@dataclass
class ControllerOptions:
    """Optional dependencies and hooks for BenchmarkController."""

    executor: RemoteExecutor | None = None
    output_callback: Callable[[str, str], None] | None = None
    output_formatter: Any | None = None
    journal_refresh: Callable[[], None] | None = None
    stop_token: StopToken | None = None
    stop_timeout_s: float = 30.0
    state_machine: ControllerStateMachine | None = None

    def build_executor(self) -> RemoteExecutor:
        if self.executor:
            return self.executor
        stream = self.output_callback is not None
        return AnsibleRunnerExecutor(
            output_callback=self.output_callback,
            stream_output=stream,
            stop_token=self.stop_token,
        )
