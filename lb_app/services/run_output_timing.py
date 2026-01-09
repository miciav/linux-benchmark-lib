"""Timing helpers for run output formatting."""

from __future__ import annotations

import time


class TaskTimer:
    """Track task durations based on Ansible task boundaries."""

    def __init__(self) -> None:
        self._task_phase: str | None = None
        self._task_message: str | None = None
        self._started_at: float | None = None

    def start(self, phase: str, message: str) -> tuple[str, str] | None:
        now = time.monotonic()
        previous = None
        if self._task_message and self._started_at is not None:
            previous = self._finish(now)
        self._task_phase = phase
        self._task_message = message
        self._started_at = now
        return previous

    def flush(self) -> tuple[str, str] | None:
        return self._finish(time.monotonic())

    def _finish(self, now: float) -> tuple[str, str] | None:
        if not self._task_message or self._started_at is None:
            return None
        elapsed = now - self._started_at
        phase = self._task_phase or "run"
        message = f"{self._task_message} done in {elapsed:.1f}s"
        self._task_phase = None
        self._task_message = None
        self._started_at = None
        return phase, message
