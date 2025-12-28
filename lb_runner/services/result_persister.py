"""Helper for persisting workload results."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lb_plugins.api import WorkloadPlugin
from lb_runner.services.results import (
    export_plugin_results,
    merge_results,
    persist_rep_result,
    persist_results,
)


class ResultPersister:
    """Persist and export workload results for a run."""

    def __init__(self, run_id: str | None = None) -> None:
        self._run_id = run_id or ""

    def set_run_id(self, run_id: str | None) -> None:
        self._run_id = run_id or ""

    def persist_rep_result(self, rep_dir: Path, result: dict[str, Any]) -> None:
        persist_rep_result(rep_dir, result)

    def process_results(
        self,
        plugin: WorkloadPlugin | None,
        results: list[dict[str, Any]],
        target_root: Path,
        test_name: str,
    ) -> None:
        results_file = target_root / f"{test_name}_results.json"
        merged_results = merge_results(results_file, results)
        persist_results(results_file, merged_results)
        export_plugin_results(
            plugin,
            merged_results,
            target_root,
            test_name,
            self._run_id,
        )
