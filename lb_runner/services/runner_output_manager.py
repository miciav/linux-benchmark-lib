"""Output management for local benchmark runs."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any

from lb_runner.models.config import BenchmarkConfig
from lb_runner.services.result_persister import ResultPersister
from lb_runner.services.storage import workload_output_dir, write_system_info_artifacts
from lb_runner.services.system_info_types import SystemInfo


@dataclass
class RunnerOutputManager:
    """Handle output directories and result persistence for local runs."""

    config: BenchmarkConfig
    persister: ResultPersister
    logger: logging.Logger

    _run_id: str | None = None
    _output_root: Path | None = None
    _data_export_root: Path | None = None

    def set_scope(
        self,
        run_id: str,
        output_root: Path | None,
        data_export_root: Path | None,
    ) -> None:
        self._run_id = run_id
        self._output_root = output_root
        self._data_export_root = data_export_root
        self.persister.set_run_id(run_id)

    def workload_output_dir(self, workload: str) -> Path:
        base = self._output_root or self.config.output_dir
        return workload_output_dir(base, workload, ensure=True)

    def output_root(self) -> Path | None:
        return self._output_root

    def write_system_info(self, collected: SystemInfo) -> None:
        if self._output_root:
            try:
                write_system_info_artifacts(
                    collected, self._output_root, self.logger
                )
            except Exception:
                self.logger.debug("Failed to write system info artifacts", exc_info=True)

    def persist_rep_result(self, rep_dir: Path, result: dict[str, Any]) -> None:
        self.persister.persist_rep_result(rep_dir, result)

    def process_results(
        self,
        *,
        plugin,
        results: list[dict[str, Any]],
        target_root: Path,
        test_name: str,
    ) -> None:
        self.persister.process_results(
            plugin=plugin,
            results=results,
            target_root=target_root,
            test_name=test_name,
        )
