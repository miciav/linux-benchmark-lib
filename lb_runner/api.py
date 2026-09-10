"""Stable runner API surface."""

from lb_runner.engine.runner import LocalRunner
from lb_runner.engine.stop_token import StopToken
from lb_runner.metric_collectors._base_collector import BaseCollector
from lb_runner.metric_collectors.aggregators import aggregate_cli
from lb_runner.models import config as config_module
from lb_runner.models.config import (
    DEFAULT_LB_WORKDIR,
    BenchmarkConfig,
    GrafanaPlatformConfig,
    LokiConfig,
    MetricCollectorConfig,
    PerfConfig,
    PlatformConfig,
    RemoteExecutionConfig,
    RemoteHostConfig,
    WorkloadConfig,
)
from lb_runner.models.events import RunEvent, StdoutEmitter
from lb_runner.registry import RunnerRegistry
from lb_runner.services import storage as storage_module
from lb_runner.services import system_info as system_info_module
from lb_runner.services.log_handler import LBEventLogHandler
from lb_runner.services.results import collect_metrics
from lb_runner.services.storage import ensure_run_dirs, workload_output_dir
from lb_runner.services.system_info_io import write_outputs

__all__ = [
    "DEFAULT_LB_WORKDIR",
    "BaseCollector",
    "BenchmarkConfig",
    "GrafanaPlatformConfig",
    "LBEventLogHandler",
    "LocalRunner",
    "LokiConfig",
    "MetricCollectorConfig",
    "PerfConfig",
    "PlatformConfig",
    "RemoteExecutionConfig",
    "RemoteHostConfig",
    "RunEvent",
    "RunnerRegistry",
    "StdoutEmitter",
    "StopToken",
    "WorkloadConfig",
    "aggregate_cli",
    "collect_metrics",
    "config_module",
    "ensure_run_dirs",
    "storage_module",
    "system_info_module",
    "workload_output_dir",
    "write_outputs",
]
