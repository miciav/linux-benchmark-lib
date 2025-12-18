"""Interfaces and value objects exposed to UI layers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Protocol, Sequence

from lb_runner.benchmark_config import BenchmarkConfig
from lb_controller.journal import RunJournal
from lb_controller.services.run_service import RunResult
from lb_controller.ui_interfaces import UIAdapter
from lb_runner.events import RunEvent


class UIHooks(Protocol):
    """Callbacks invoked by the application layer to update the UI."""

    def on_log(self, line: str) -> None: ...
    def on_status(self, controller_state: str) -> None: ...
    def on_warning(self, message: str, ttl: float = 10.0) -> None: ...
    def on_event(self, event: RunEvent) -> None: ...
    def on_journal(self, journal: RunJournal) -> None: ...


@dataclass
class RunRequest:
    """Inputs required to start a run from the UI."""

    config: BenchmarkConfig
    tests: Sequence[str]
    run_id: str | None = None
    resume: str | None = None
    debug: bool = False
    intensity: str | None = None
    setup: bool = True
    stop_file: Path | None = None
    execution_mode: str = "remote"
    repetitions: int | None = None
    node_count: int = 1
    docker_engine: str = "docker"
    ui_adapter: UIAdapter | None = None


class AppClient(Protocol):
    """Minimal interface that the UI can call into."""

    def load_config(self, path: Path | None = None) -> BenchmarkConfig: ...
    def save_config(self, config: BenchmarkConfig, path: Path) -> None: ...
    def list_runs(self, config: BenchmarkConfig) -> Iterable[RunJournal]: ...
    def get_run_plan(self, config: BenchmarkConfig, tests: Sequence[str], execution_mode: str = "remote"): ...
    def start_run(self, request: RunRequest, hooks: UIHooks) -> RunResult | None: ...
