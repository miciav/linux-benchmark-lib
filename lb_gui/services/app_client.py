"""Thin wrapper around lb_app.api.ApplicationClient."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from lb_app.api import ApplicationClient, BenchmarkConfig, RunRequest, UIHooks

if TYPE_CHECKING:
    from lb_app.api import RunResult


class AppClientService:
    """Service holding the ApplicationClient instance."""

    def __init__(self) -> None:
        self._client = ApplicationClient()

    @property
    def client(self) -> ApplicationClient:
        """Access the underlying ApplicationClient."""
        return self._client

    def load_config(self, path: Path | None = None) -> BenchmarkConfig:
        """Load benchmark configuration from path or default location."""
        return self._client.load_config(path)

    def save_config(self, config: BenchmarkConfig, path: Path) -> None:
        """Save benchmark configuration to path."""
        self._client.save_config(config, path)

    def get_run_plan(
        self,
        config: BenchmarkConfig,
        tests: list[str],
        execution_mode: str = "remote",
    ) -> list[dict[str, object]]:
        """Get the run plan for given tests."""
        return self._client.get_run_plan(config, tests, execution_mode)

    def start_run(
        self,
        request: RunRequest,
        hooks: UIHooks,
    ) -> RunResult | None:
        """Start a benchmark run. Returns None on validation failure."""
        return self._client.start_run(request, hooks)
