"""Helpers for persisting run results and metrics."""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from json import JSONEncoder
from pathlib import Path
from typing import Any

from lb_plugins.api import WorkloadPlugin


logger = logging.getLogger(__name__)


class DateTimeEncoder(JSONEncoder):
    """Custom JSON encoder that handles datetime objects."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def build_rep_result(
    test_name: str,
    repetition: int,
    rep_dir: Path,
    generator_result: Any,
    test_start_time: datetime | None,
    test_end_time: datetime | None,
) -> dict[str, Any]:
    """Assemble the base result payload for a single repetition."""
    duration_seconds = (
        (test_end_time - test_start_time).total_seconds()
        if test_start_time and test_end_time
        else 0
    )

    result = {
        "test_name": test_name,
        "repetition": repetition,
        "start_time": test_start_time.isoformat() if test_start_time else None,
        "end_time": test_end_time.isoformat() if test_end_time else None,
        "duration_seconds": duration_seconds,
        "generator_result": generator_result,
        "metrics": {},
        "artifacts_dir": str(rep_dir),
    }
    result["success"] = is_generator_success(generator_result)
    return result


def is_generator_success(gen_result: Any) -> bool:
    if isinstance(gen_result, dict):
        if gen_result.get("error"):
            return False
        rc = gen_result.get("returncode")
        return rc in (None, 0)
    return gen_result in (None, 0, True)


def collect_metrics(
    collectors: list[Any],
    workload_dir: Path,
    rep_dir: Path,
    test_name: str,
    repetition: int,
    result: dict[str, Any],
) -> None:
    for collector in collectors:
        collector_data = collector.get_data()
        result["metrics"][collector.name] = collector_data
        filename = f"{test_name}_rep{repetition}_{collector.name}.csv"
        rep_filepath = rep_dir / filename
        collector.save_data(rep_filepath)


def persist_rep_result(rep_dir: Path, result: dict[str, Any]) -> None:
    try:
        rep_result_path = rep_dir / "result.json"
        rep_result_path.write_text(json.dumps(result, indent=2, cls=DateTimeEncoder))
    except Exception:
        pass


def merge_results(
    results_file: Path,
    new_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    if results_file.exists():
        try:
            existing_raw = json.loads(results_file.read_text())
            if isinstance(existing_raw, list):
                merged = [r for r in existing_raw if isinstance(r, dict)]
        except Exception:
            merged = []

    def _rep_key(entry: dict[str, Any]) -> int | None:
        rep_val = entry.get("repetition")
        return rep_val if isinstance(rep_val, int) and rep_val > 0 else None

    merged_by_rep: dict[int, dict[str, Any]] = {
        rep: entry for entry in merged if (rep := _rep_key(entry)) is not None
    }
    unkeyed: list[dict[str, Any]] = [e for e in merged if _rep_key(e) is None]
    for entry in new_results:
        rep = _rep_key(entry)
        if rep is None:
            unkeyed.append(entry)
        else:
            merged_by_rep[rep] = entry

    return [merged_by_rep[rep] for rep in sorted(merged_by_rep)] + unkeyed


def persist_results(results_file: Path, merged_results: list[dict[str, Any]]) -> None:
    tmp_path = results_file.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(merged_results, indent=2, cls=DateTimeEncoder))
    tmp_path.replace(results_file)
    logger.info("Saved raw results to %s", results_file)


def export_plugin_results(
    plugin: WorkloadPlugin | None,
    merged_results: list[dict[str, Any]],
    target_root: Path,
    test_name: str,
    run_id: str,
) -> None:
    if not plugin:
        return
    try:
        exported = plugin.export_results_to_csv(
            results=merged_results,
            output_dir=target_root,
            run_id=run_id,
            test_name=test_name,
        )
        for path in exported:
            logger.info("Plugin exported CSV: %s", path)
    except Exception as exc:
        logger.warning("Plugin '%s' export_results_to_csv failed: %s", plugin.name, exc)
