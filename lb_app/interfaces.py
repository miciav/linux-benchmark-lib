"""Interfaces and value objects exposed to UI layers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol, Sequence

from lb_controller.api import BenchmarkConfig, RunEvent
from lb_controller.api import RunJournal
from lb_app.services.run_service import RunResult
from lb_app.services.provision_service import ProvisionConfigSummary, ProvisionStatus
from lb_app.ui_interfaces import UIAdapter


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
    def install_loki_grafana(
        self,
        *,
        mode: str,
        config_path: Path | None,
        grafana_url: str | None,
        grafana_api_key: str | None,
        grafana_org_id: int | None,
        loki_endpoint: str | None,
        configure_assets: bool = True,
    ) -> ProvisionConfigSummary | None: ...
    def remove_loki_grafana(self, *, remove_data: bool = False) -> None: ...
    def status_loki_grafana(
        self,
        *,
        grafana_url: str | None,
        grafana_api_key: str | None,
        grafana_org_id: int | None,
        loki_endpoint: str | None,
    ) -> ProvisionStatus: ...
