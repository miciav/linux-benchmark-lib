"""Stable runner API surface."""

from lb_runner.models.config import (
    BenchmarkConfig,
    RemoteExecutionConfig,
    RemoteHostConfig,
    WorkloadConfig,
)
from lb_runner.models.events import RunEvent, StdoutEmitter
from lb_runner.plugin_system.base_generator import BaseGenerator
from lb_runner.plugin_system.interface import WorkloadIntensity, WorkloadPlugin
from lb_runner.plugin_system.registry import PluginRegistry

__all__ = [
    "BenchmarkConfig",
    "RemoteExecutionConfig",
    "RemoteHostConfig",
    "WorkloadConfig",
    "BaseGenerator",
    "WorkloadIntensity",
    "WorkloadPlugin",
    "PluginRegistry",
    "RunEvent",
    "StdoutEmitter",
]
