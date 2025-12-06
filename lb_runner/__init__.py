"""Runner facade for linux-benchmark-lib components.

This module re-exports runner-facing types so we can start publishing a
lightweight runner package without moving code yet.
"""

from lb_runner.benchmark_config import BenchmarkConfig
from lb_runner.events import ProgressEmitter, RunEvent, StdoutEmitter
from lb_runner.local_runner import LocalRunner
from lb_runner.plugin_system.base_generator import BaseGenerator
from lb_runner.plugin_system.interface import WorkloadIntensity, WorkloadPlugin
from lb_runner.plugin_system.registry import PluginRegistry

__all__ = [
    "BenchmarkConfig",
    "LocalRunner",
    "BaseGenerator",
    "PluginRegistry",
    "WorkloadIntensity",
    "WorkloadPlugin",
    "RunEvent",
    "ProgressEmitter",
    "StdoutEmitter",
]
