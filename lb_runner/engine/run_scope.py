"""Run scope preparation helpers for the local runner."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path

from lb_runner.engine.planning import generate_run_id
from lb_runner.models.config import BenchmarkConfig
from lb_runner.services.storage import ensure_run_dirs, ensure_runner_log


@dataclass(frozen=True)
class RunScope:
    """Resolved directories and identifiers for a benchmark run."""

    run_id: str
    output_root: Path
    data_export_root: Path
    report_root: Path


class RunScopeManager:
    """Create output scopes and attach run-level logging."""

    def __init__(self, config: BenchmarkConfig, logger: logging.Logger) -> None:
        self._config = config
        self._logger = logger
        self._log_attached = False

    def prepare(self, run_id: str | None = None) -> RunScope:
        resolved_id = run_id or generate_run_id()
        output_root, data_export_root, report_root = ensure_run_dirs(
            self._config, resolved_id
        )
        if not self._log_attached:
            self._log_attached = ensure_runner_log(output_root, self._logger)
        return RunScope(
            run_id=resolved_id,
            output_root=output_root,
            data_export_root=data_export_root,
            report_root=report_root,
        )
