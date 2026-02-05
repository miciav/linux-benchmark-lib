"""RunSession encapsulates the state of a single execution."""

from __future__ import annotations

import logging
from typing import Optional

from lb_controller.engine.run_state import RunState
from lb_controller.engine.stops import StopCoordinator
from lb_controller.models.state import ControllerState, ControllerStateMachine

logger = logging.getLogger(__name__)


class RunSession:
    """
    Encapsulates all state for a single benchmark run.

    Includes:
    - Static configuration state (RunState)
    - Dynamic control state (ControllerStateMachine)
    - Process synchronization (StopCoordinator)
    """

    def __init__(
        self,
        state: RunState,
        stop_coordinator: Optional[StopCoordinator] = None,
        state_machine: Optional[ControllerStateMachine] = None,
    ):
        self.state = state
        self.coordinator = stop_coordinator
        self.state_machine = state_machine or ControllerStateMachine()

    @property
    def run_id(self) -> str:
        return self.state.resolved_run_id

    def transition(self, state: ControllerState, reason: str | None = None) -> None:
        """Transition the internal state machine."""
        try:
            self.state_machine.transition(state, reason=reason)
        except ValueError:
            logger.debug(
                "Invalid transition ignored: %s -> %s",
                self.state_machine.state,
                state,
            )

    def arm_stop(self, reason: str | None = None) -> None:
        """Arm the stop mechanism."""
        try:
            self.state_machine.transition(ControllerState.STOP_ARMED, reason=reason)
        except Exception:
            pass

    def allows_cleanup(self) -> bool:
        return self.state_machine.allows_cleanup()
