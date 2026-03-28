"""Helper for persisting workload results."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lb_plugins.api import WorkloadPlugin
from lb_runner.services.results import (
    export_plugin_results,
    merge_result_entries,
    merge_results,
    persist_rep_result,
    persist_results,
)


class ResultPersister:
    """Persist and export workload results for a run."""

    def __init__(self, run_id: str | None = None) -> None:
        self._run_id = run_id or ""
        self._merged_results: dict[Path, list[dict[str, Any]]] = {}

    def set_run_id(self, run_id: str | None) -> None:
        self._run_id = run_id or ""
        self._merged_results.clear()

    def persist_rep_result(self, rep_dir: Path, result: dict[str, Any]) -> None:
        persist_rep_result(rep_dir, result)

    def process_results(
        self,
        plugin: WorkloadPlugin | None,
        results: list[dict[str, Any]],
        target_root: Path,
        test_name: str,
        *,
        export_results: bool = True,
    ) -> None:
        results_file = target_root / f"{test_name}_results.json"
        merged_results = self._merge_results(results_file, results)
        if not merged_results and not results_file.exists():
            self._merged_results.pop(results_file, None)
            return

        persist_results(results_file, merged_results)
        if export_results:
            export_plugin_results(
                plugin,
                merged_results,
                target_root,
                test_name,
                self._run_id,
            )
            self._merged_results.pop(results_file, None)

    def _merge_results(
        self, results_file: Path, new_results: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        cached = self._merged_results.get(results_file)
        if cached is None:
            merged = merge_results(results_file, new_results)
        else:
            merged = merge_result_entries(cached, new_results)
        self._merged_results[results_file] = merged
        return merged
