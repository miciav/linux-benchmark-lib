"""Runner facade for linux-benchmark-lib components.

This module re-exports runner-facing types so we can start publishing a
lightweight runner package without moving code yet.
"""

from linux_benchmark_lib.benchmark_config import BenchmarkConfig
from linux_benchmark_lib.events import ProgressEmitter, RunEvent, StdoutEmitter
from linux_benchmark_lib.local_runner import LocalRunner
from linux_benchmark_lib.plugin_system.base_generator import BaseGenerator
from linux_benchmark_lib.plugin_system.interface import WorkloadIntensity, WorkloadPlugin
from linux_benchmark_lib.plugin_system.registry import PluginRegistry

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
