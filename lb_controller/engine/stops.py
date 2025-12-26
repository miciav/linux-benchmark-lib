"""
Coordinator for distributed stop protocol.

Manages the lifecycle of a graceful stop:
1. Requesting remote runners to stop (via Stop File).
2. Waiting for confirmation events.
3. Deciding whether to proceed to teardown.
"""

import time
import logging
from enum import Enum, auto
from typing import Set, Dict, Any

from lb_runner.api import RunEvent

logger = logging.getLogger(__name__)


class StopState(Enum):
    IDLE = auto()
    STOPPING_WORKLOADS = auto()  # Request sent, waiting for runners
    TEARDOWN_READY = auto()      # All runners confirmed stop
    STOP_FAILED = auto()         # Timeout or failure in stop protocol


class StopCoordinator:
    def __init__(
        self,
        expected_runners: Set[str],
        stop_timeout: float = 30.0,
        run_id: str | None = None,
    ):
        """
        Args:
            expected_runners: Set of hostnames expected to confirm stop.
            stop_timeout: Seconds to wait for confirmations.
            run_id: Run identifier used to correlate stop events.
        """
        self.expected_runners = expected_runners
        self.confirmed_runners: Set[str] = set()
        self.state = StopState.IDLE
        self.stop_timeout = stop_timeout
        self.start_time: float | None = None
        self.run_id = run_id
        
    def initiate_stop(self) -> None:
        """Transition to STOPPING_WORKLOADS."""
        if self.state != StopState.IDLE:
            return
        logger.info("Initiating distributed stop protocol.")
        self.state = StopState.STOPPING_WORKLOADS
        self.start_time = time.time()
        # The caller is responsible for actually deploying the stop file via Ansible
        # immediately after calling this.

    def process_event(self, event: RunEvent) -> None:
        """
        Process incoming events to check for stop confirmation.
        
        We accept 'stopped', 'failed', or 'cancelled' as confirmation that 
        the runner has ceased execution for the current workload.
        """
        if self.state != StopState.STOPPING_WORKLOADS:
            return

        if self.run_id and getattr(event, "run_id", None) and event.run_id != self.run_id:
            return

        if event.host not in self.expected_runners:
            return

        # Check for status indicating the workload has stopped/aborted
        # Note: 'failed' is often emitted on interrupt. 'stopped' is ideal.
        if event.status.lower() in ("stopped", "failed", "cancelled", "done"):
            if event.host not in self.confirmed_runners:
                logger.info(f"Stop confirmed for host: {event.host} (status={event.status})")
                self.confirmed_runners.add(event.host)
                self._check_completion()

    def _check_completion(self) -> None:
        """Check if all expected runners have confirmed."""
        if self.expected_runners.issubset(self.confirmed_runners):
            logger.info("All runners confirmed stop. Ready for teardown.")
            self.state = StopState.TEARDOWN_READY

    def check_timeout(self) -> None:
        """Check if the stop protocol has timed out."""
        if self.state != StopState.STOPPING_WORKLOADS:
            return
        
        if self.start_time and (time.time() - self.start_time > self.stop_timeout):
            missing = self.expected_runners - self.confirmed_runners
            logger.error(f"Stop protocol timed out. Missing confirmations from: {missing}")
            self.state = StopState.STOP_FAILED

    def can_proceed_to_teardown(self) -> bool:
        return self.state == StopState.TEARDOWN_READY
