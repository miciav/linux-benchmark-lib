"""Stable runner API surface."""

from lb_runner.models.config import (
    DEFAULT_LB_WORKDIR,
    BenchmarkConfig,
    GrafanaPlatformConfig,
    MetricCollectorConfig,
    PerfConfig,
    PlatformConfig,
    RemoteExecutionConfig,
    RemoteHostConfig,
    WorkloadConfig,
)
from lb_runner.models import config as config_module
from lb_runner.models.events import RunEvent, StdoutEmitter
from lb_runner.engine.runner import LocalRunner
from lb_runner.engine.stop_token import StopToken
from lb_runner.metric_collectors._base_collector import BaseCollector
from lb_runner.metric_collectors.aggregators import aggregate_cli
from lb_runner.registry import RunnerRegistry
from lb_runner.services.log_handler import LBEventLogHandler
from lb_runner.services.results import collect_metrics
from lb_runner.services import storage as storage_module
from lb_runner.services import system_info as system_info_module
from lb_runner.services.storage import ensure_run_dirs, workload_output_dir
from lb_runner.services.system_info_io import write_outputs

__all__ = [
    "BenchmarkConfig",
    "DEFAULT_LB_WORKDIR",
    "GrafanaPlatformConfig",
    "MetricCollectorConfig",
    "PerfConfig",
    "PlatformConfig",
    "RemoteExecutionConfig",
    "RemoteHostConfig",
    "WorkloadConfig",
    "BaseCollector",
    "RunEvent",
    "StdoutEmitter",
    "LocalRunner",
    "LBEventLogHandler",
    "collect_metrics",
    "aggregate_cli",
    "ensure_run_dirs",
    "write_outputs",
    "config_module",
    "storage_module",
    "system_info_module",
    "StopToken",
    "workload_output_dir",
    "RunnerRegistry",
]
