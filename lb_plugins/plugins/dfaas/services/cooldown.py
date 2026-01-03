"""Cooldown manager service for DFaaS plugin."""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MetricsSnapshot:
    """Snapshot of node metrics at a point in time."""

    cpu: float
    ram: float
    ram_pct: float
    power: float


@dataclass
class CooldownResult:
    """Result of a cooldown wait operation."""

    snapshot: MetricsSnapshot
    waited_seconds: int
    iterations: int


class CooldownTimeoutError(TimeoutError):
    """Raised when cooldown exceeds maximum wait time."""

    def __init__(self, waited_seconds: int, max_seconds: int) -> None:
        self.waited_seconds = waited_seconds
        self.max_seconds = max_seconds
        super().__init__(
            f"Cooldown timeout after {waited_seconds}s (max: {max_seconds}s)"
        )


class CooldownManager:
    """Manages cooldown waits between benchmark configurations.

    Waits until system metrics return to baseline levels before
    allowing the next configuration to run.

    The manager uses injectable provider functions to:
    - Query current node metrics (CPU, RAM, power)
    - Query function replica counts
    """

    def __init__(
        self,
        max_wait_seconds: int,
        sleep_step_seconds: int,
        idle_threshold_pct: float,
        metrics_provider: Callable[[], MetricsSnapshot],
        replicas_provider: Callable[[list[str]], dict[str, int]],
    ) -> None:
        """Initialize CooldownManager.

        Args:
            max_wait_seconds: Maximum time to wait for cooldown
            sleep_step_seconds: Time to sleep between checks
            idle_threshold_pct: Percentage threshold above baseline (0-100)
            metrics_provider: Function that returns current MetricsSnapshot
            replicas_provider: Function that returns replica counts by function name
        """
        self.max_wait_seconds = max_wait_seconds
        self.sleep_step_seconds = sleep_step_seconds
        self.idle_threshold_pct = idle_threshold_pct / 100.0  # Convert to fraction
        self._metrics_provider = metrics_provider
        self._replicas_provider = replicas_provider

    def wait_for_idle(
        self,
        baseline: MetricsSnapshot,
        function_names: list[str],
    ) -> CooldownResult:
        """Wait until system returns to idle state.

        Args:
            baseline: Baseline metrics to compare against
            function_names: Function names to check replica counts

        Returns:
            CooldownResult with final snapshot and wait statistics

        Raises:
            CooldownTimeoutError: If max_wait_seconds exceeded
        """
        waited = 0
        iterations = 0

        while True:
            iterations += 1
            snapshot = self._metrics_provider()
            replicas = self._replicas_provider(function_names)

            if self._is_idle(snapshot, baseline, replicas):
                logger.debug(
                    "Cooldown complete after %ds (%d iterations)",
                    waited,
                    iterations,
                )
                return CooldownResult(
                    snapshot=snapshot,
                    waited_seconds=waited,
                    iterations=iterations,
                )

            time.sleep(self.sleep_step_seconds)
            waited += self.sleep_step_seconds

            if waited > self.max_wait_seconds:
                raise CooldownTimeoutError(waited, self.max_wait_seconds)

    def _is_idle(
        self,
        current: MetricsSnapshot,
        baseline: MetricsSnapshot,
        replicas: dict[str, int],
    ) -> bool:
        """Check if system is in idle state.

        Returns True if:
        - CPU is within threshold of baseline
        - RAM is within threshold of baseline
        - Power is within threshold of baseline (or NaN)
        - All function replicas are < 2
        """
        replicas_ok = all(value < 2 for value in replicas.values())

        return (
            self.is_within_threshold(current.cpu, baseline.cpu)
            and self.is_within_threshold(current.ram, baseline.ram)
            and self.is_within_threshold(current.power, baseline.power)
            and replicas_ok
        )

    def is_within_threshold(self, value: float, baseline: float) -> bool:
        """Check if value is within threshold of baseline.

        Args:
            value: Current metric value
            baseline: Baseline metric value

        Returns:
            True if value <= baseline + (baseline * threshold_pct)
            Also returns True if either value is NaN
        """
        if math.isnan(baseline) or math.isnan(value):
            return True
        return value <= baseline + (baseline * self.idle_threshold_pct)


def within_threshold(value: float, baseline: float, threshold_pct: float) -> bool:
    """Standalone threshold check function.

    Args:
        value: Current metric value
        baseline: Baseline metric value
        threshold_pct: Threshold as fraction (0.0 to 1.0)

    Returns:
        True if value is within threshold of baseline
    """
    if math.isnan(baseline) or math.isnan(value):
        return True
    return value <= baseline + (baseline * threshold_pct)
