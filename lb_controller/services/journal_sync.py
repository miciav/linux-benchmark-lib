"""Helpers for journal updates and result backfill."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from lb_runner.api import RemoteHostConfig

from lb_controller.services.journal import RunJournal, RunStatus, TaskState

logger = logging.getLogger(__name__)


def update_journal_tasks(
    journal: RunJournal,
    journal_path: Path,
    hosts: list[RemoteHostConfig],
    workload: str,
    repetition: int,
    status: str,
    action: str | None = None,
    error: str | None = None,
    refresh: Callable[[], None] | None = None,
    *,
    persist: bool = True,
) -> None:
    """Update journal entries for each host and persist."""
    for host in hosts:
        journal.update_task(
            host.name,
            workload,
            repetition,
            status,
            action=action or "",
            error=error,
        )
    if persist:
        journal.save(journal_path)
        _refresh_journal(refresh)


def update_all_reps(
    repetitions: int,
    journal: RunJournal,
    journal_path: Path,
    hosts: list[RemoteHostConfig],
    workload: str,
    status: str,
    action: str | None = None,
    error: str | None = None,
    refresh: Callable[[], None] | None = None,
) -> None:
    """Update journal for all repetitions of a workload."""
    if not journal:
        return
    for rep in range(1, repetitions + 1):
        update_journal_tasks(
            journal,
            journal_path,
            hosts,
            workload,
            rep,
            status,
            action=action,
            error=error,
            refresh=None,
            persist=False,
        )
    journal.save(journal_path)
    _refresh_journal(refresh)


def backfill_timings_from_results(
    journal: RunJournal,
    journal_path: Path,
    hosts: list[RemoteHostConfig],
    workload: str,
    per_host_output: dict[str, Path],
    refresh: Callable[[], None] | None = None,
) -> None:
    """Backfill per-repetition timing data from all *_results.json artifacts."""
    updated = False
    for host in hosts:
        entries = _collect_results(per_host_output.get(host.name), workload)
        for entry in entries:
            updated |= _apply_result_entry(journal, host.name, workload, entry)
    if updated:
        journal.save(journal_path)
        _refresh_journal(refresh)


def _refresh_journal(refresh: Callable[[], None] | None) -> None:
    """Trigger UI refresh when a journal update occurs."""
    if refresh:
        refresh()


def _collect_results(host_dir: Path | None, workload: str) -> list[dict[str, Any]]:
    """Return parsed results entries for a host/workload."""
    if not host_dir:
        return []
    candidates = sorted(
        host_dir.rglob(f"{workload}_results.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    entries: list[dict[str, Any]] = []
    for results_file in candidates:
        try:
            loaded = json.loads(results_file.read_text()) or []
        except Exception as exc:
            logger.debug("Failed to parse results at %s: %s", results_file, exc)
            continue
        if isinstance(loaded, list):
            entries.extend(item for item in loaded if isinstance(item, dict))
    return entries


def _apply_result_entry(
    journal: RunJournal, host: str, workload: str, entry: dict[str, Any]
) -> bool:
    """Update a journal task from a single results entry."""
    rep = entry.get("repetition")
    if rep is None:
        return False
    task = journal.get_task(host, workload, rep)
    if not task:
        return False

    _update_task_timings(task, entry)
    _update_task_status(task, entry)
    return True


def _update_task_timings(task: TaskState, entry: dict[str, Any]) -> None:
    start_str = entry.get("start_time")
    end_str = entry.get("end_time")
    if start_str:
        task.started_at = datetime.fromisoformat(start_str).timestamp()
    if end_str:
        task.finished_at = datetime.fromisoformat(end_str).timestamp()
    duration = entry.get("duration_seconds")
    if duration is not None:
        task.duration_seconds = float(duration)
    elif task.started_at is not None and task.finished_at is not None:
        task.duration_seconds = max(0.0, task.finished_at - task.started_at)


def _update_task_status(task: TaskState, entry: dict[str, Any]) -> None:
    gen_result = entry.get("generator_result") or {}
    gen_error = gen_result.get("error")
    gen_rc = gen_result.get("returncode")
    entry_error_type = entry.get("error_type")
    entry_error_context = entry.get("error_context")
    if gen_error or (gen_rc not in (None, 0)):
        task.status = RunStatus.FAILED
        error_message = _format_error_message(gen_error, gen_rc, gen_result)
        task.current_action = task.error = error_message
        task.error_type = entry_error_type
        task.error_context = entry_error_context
        return
    if entry_error_type:
        task.status = RunStatus.FAILED
        task.current_action = task.error = entry.get("error") or "error recorded"
        task.error_type = entry_error_type
        task.error_context = entry_error_context
        return
    if task.status not in (RunStatus.FAILED, RunStatus.SKIPPED):
        task.status = RunStatus.COMPLETED


def _format_error_message(
    gen_error: str | None, gen_rc: int | None, gen_result: dict[str, Any]
) -> str:
    err_parts = []
    if gen_error:
        err_parts.append(str(gen_error))
    if gen_rc not in (None, 0):
        err_parts.append(f"returncode={gen_rc}")
    cmd = gen_result.get("command")
    if cmd:
        err_parts.append(f"cmd={cmd}")
    return " | ".join(err_parts) if err_parts else "Workload reported an error"
