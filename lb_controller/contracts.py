"""Stable types exposed to the UI layer."""

from __future__ import annotations

from lb_runner.benchmark_config import BenchmarkConfig, RemoteHostConfig, WorkloadConfig, RemoteExecutionConfig
from lb_runner.plugin_system.registry import PluginRegistry

__all__ = [
    "BenchmarkConfig",
    "RemoteHostConfig",
    "WorkloadConfig",
    "RemoteExecutionConfig",
    "PluginRegistry",
]
