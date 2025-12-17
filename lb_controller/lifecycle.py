"""Run lifecycle state machine for phase-aware interruption."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class RunPhase(Enum):
    """High-level run phases."""

    IDLE = auto()
    GLOBAL_SETUP = auto()
    WORKLOADS = auto()
    GLOBAL_TEARDOWN = auto()
    FINISHED = auto()


class StopStage(Enum):
    """Stages of a coordinated stop."""

    IDLE = auto()
    ARMED = auto()
    INTERRUPTING_SETUP = auto()
    WAITING_FOR_RUNNERS = auto()
    INTERRUPTING_TEARDOWN = auto()
    TEARDOWN = auto()
    STOPPED = auto()
    FAILED = auto()


@dataclass
class RunLifecycle:
    """Tracks the lifecycle phase and stop intent."""

    phase: RunPhase = RunPhase.IDLE
    stop_stage: StopStage = StopStage.IDLE

    def start_phase(self, phase: RunPhase) -> None:
        self.phase = phase

    def finish(self) -> None:
        self.phase = RunPhase.FINISHED
        if self.stop_stage not in (StopStage.FAILED, StopStage.STOPPED):
            self.stop_stage = StopStage.STOPPED if self.stop_stage != StopStage.IDLE else StopStage.IDLE

    def arm_stop(self) -> None:
        if self.stop_stage == StopStage.IDLE:
            self.stop_stage = StopStage.ARMED

    def mark_interrupting_setup(self) -> None:
        self.stop_stage = StopStage.INTERRUPTING_SETUP

    def mark_waiting_runners(self) -> None:
        self.stop_stage = StopStage.WAITING_FOR_RUNNERS

    def mark_teardown(self) -> None:
        self.stop_stage = StopStage.TEARDOWN

    def mark_interrupting_teardown(self) -> None:
        self.stop_stage = StopStage.INTERRUPTING_TEARDOWN

    def mark_failed(self) -> None:
        self.stop_stage = StopStage.FAILED

    def mark_stopped(self) -> None:
        self.stop_stage = StopStage.STOPPED
