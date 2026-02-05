"""Stateless services container for the controller."""

from __future__ import annotations

from typing import Any, Callable

from lb_controller.engine.lifecycle import RunLifecycle
from lb_controller.models.types import RemoteExecutor
from lb_runner.api import BenchmarkConfig, StopToken


class ControllerServices:
    """Immutable container for stateless controller services."""

    def __init__(
        self,
        config: BenchmarkConfig,
        executor: RemoteExecutor,
        *,
        output_formatter: Any | None = None,
        stop_token: StopToken | None = None,
        lifecycle: RunLifecycle | None = None,
        journal_refresh: Callable[[], None] | None = None,
        use_progress_stream: bool = True,
    ) -> None:
        self.config = config
        self.executor = executor
        self.output_formatter = output_formatter
        self.stop_token = stop_token
        self.lifecycle = lifecycle or RunLifecycle()
        self.journal_refresh = journal_refresh
        self.use_progress_stream = use_progress_stream
