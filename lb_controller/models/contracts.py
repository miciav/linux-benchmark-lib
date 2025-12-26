"""Stable types exposed to the UI layer."""

from __future__ import annotations

from lb_runner.api import (
    BenchmarkConfig,
    RemoteExecutionConfig,
    RemoteHostConfig,
    WorkloadConfig,
)

__all__ = [
    "BenchmarkConfig",
    "RemoteHostConfig",
    "WorkloadConfig",
    "RemoteExecutionConfig",
]
