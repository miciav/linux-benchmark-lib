"""ExecutionContext for the runner."""

from __future__ import annotations
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lb_runner.models.config import BenchmarkConfig
    from lb_runner.services.runner_output_manager import RunnerOutputManager
    from lb_runner.services.runner_log_manager import RunnerLogManager
    from lb_runner.engine.stop_token import StopToken
    from lb_runner.engine.metrics import MetricManager

@dataclass
class RunnerContext:
    """Context object encapsulating request-scoped dependencies for execution."""
    
    run_id: str | None
    config: BenchmarkConfig
    output_manager: RunnerOutputManager
    log_manager: RunnerLogManager
    metric_manager: MetricManager
    stop_token: StopToken | None = None
    host_name: str | None = None
