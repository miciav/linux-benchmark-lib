"""Teardown helpers for controller runs."""

from __future__ import annotations

from collections.abc import Callable

from lb_controller.adapters.playbooks import run_global_teardown
from lb_controller.engine.run_state import RunFlags, RunState
from lb_controller.engine.session import RunSession
from lb_controller.models.types import ExecutionResult
from lb_controller.services.services import ControllerServices


class TeardownService:
    """Handle teardown operations for a run."""

    def __init__(self) -> None:
        pass

    def run_global_teardown(
        self,
        services: ControllerServices,
        session: RunSession,
        state: RunState,
        phases: dict[str, ExecutionResult],
        flags: RunFlags,
        ui_log: Callable[[str], None],
    ) -> None:
        run_global_teardown(services, session, state, phases, flags, ui_log)
