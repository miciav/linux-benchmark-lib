"""Teardown helpers for controller runs."""

from __future__ import annotations

from typing import Callable, Dict

from lb_controller.adapters.playbooks import run_global_teardown
from lb_controller.engine.run_state import RunFlags, RunState
from lb_controller.models.types import ExecutionResult
from lb_controller.services.controller_context import ControllerContext


class TeardownService:
    """Handle teardown operations for a run."""

    def __init__(self, context: ControllerContext) -> None:
        self._context = context

    def run_global_teardown(
        self,
        state: RunState,
        phases: Dict[str, ExecutionResult],
        flags: RunFlags,
        ui_log: Callable[[str], None],
    ) -> None:
        run_global_teardown(self._context, state, phases, flags, ui_log)
