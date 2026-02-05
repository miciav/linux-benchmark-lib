"""Runtime context utilities for DFaaS execution."""

from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass
class ExecutionContext:
    """Encapsulates runtime context for DFaaS execution."""

    host: str
    repetition: int
    total_repetitions: int
    event_logging_enabled: bool = False
    host_address: str | None = None

    @classmethod
    def from_environment(cls) -> "ExecutionContext":
        """Create context from environment variables."""
        host = os.environ.get("LB_RUN_HOST") or os.uname().nodename
        host_address = os.environ.get("LB_RUN_HOST_ADDRESS")
        repetition = _parse_int(os.environ.get("LB_RUN_REPETITION"), 1)
        total = _parse_int(os.environ.get("LB_RUN_TOTAL_REPS"), repetition)
        raw = os.environ.get("LB_ENABLE_EVENT_LOGGING", "1").strip().lower()
        event_logging = raw not in {"0", "false", "no"}
        return cls(
            host=host,
            repetition=repetition,
            total_repetitions=total,
            event_logging_enabled=event_logging,
            host_address=host_address,
        )


def _parse_int(value: str | None, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default
