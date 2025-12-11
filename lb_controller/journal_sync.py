"""Helpers for journal updates and result backfill."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from lb_runner.benchmark_config import RemoteHostConfig

from lb_controller.journal import RunJournal, RunStatus

logger = logging.getLogger(__name__)


def update_journal_tasks(
    journal: RunJournal,
    journal_path: Path,
    hosts: List[RemoteHostConfig],
    workload: str,
    repetition: int,
    status: str,
    action: Optional[str] = None,
    error: Optional[str] = None,
    refresh: Optional[callable] = None,
) -> None:
    """Update journal entries for each host and persist."""
    for host in hosts:
        journal.update_task(
            host.name,
            workload,
            repetition,
            status,
            action=action,
            error=error,
        )
    journal.save(journal_path)
    _refresh_journal(refresh)


def update_all_reps(
    repetitions: int,
    journal: RunJournal,
    journal_path: Path,
    hosts: List[RemoteHostConfig],
    workload: str,
    status: str,
    action: Optional[str] = None,
    error: Optional[str] = None,
    refresh: Optional[callable] = None,
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
            refresh=refresh,
        )


def backfill_timings_from_results(
    journal: RunJournal,
    journal_path: Path,
    hosts: List[RemoteHostConfig],
    workload: str,
    per_host_output: Dict[str, Path],
    refresh: Optional[callable] = None,
) -> None:
    """Backfill per-repetition timing data from all *_results.json artifacts."""
    updated = False
    for host in hosts:
        host_dir = per_host_output.get(host.name)
        if not host_dir:
            continue
        candidates = sorted(
            host_dir.rglob(f"{workload}_results.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            continue
        for results_file in candidates:
            try:
                entries = json.loads(results_file.read_text())
            except Exception as exc:
                logger.debug("Failed to parse results for %s: %s", host.name, exc)
                continue
            for entry in entries or []:
                rep = entry.get("repetition")
                if rep is None:
                    continue
                task = journal.get_task(host.name, workload, rep)
                if not task:
                    continue
                try:
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
                    gen_result = entry.get("generator_result") or {}
                    gen_error = gen_result.get("error")
                    gen_rc = gen_result.get("returncode")
                    if gen_error or (gen_rc not in (None, 0)):
                        task.status = RunStatus.FAILED
                        err_parts = []
                        if gen_error:
                            err_parts.append(str(gen_error))
                        if gen_rc not in (None, 0):
                            err_parts.append(f"returncode={gen_rc}")
                        cmd = gen_result.get("command")
                        if cmd:
                            err_parts.append(f"cmd={cmd}")
                        message = " | ".join(err_parts) if err_parts else "Workload reported an error"
                        task.current_action = message
                        task.error = message
                    elif task.status not in (RunStatus.FAILED, RunStatus.SKIPPED):
                        task.status = RunStatus.COMPLETED
                    updated = True
                except Exception as exc:
                    logger.debug("Failed to backfill timing for %s rep %s: %s", host.name, rep, exc)
    if updated:
        journal.save(journal_path)
        _refresh_journal(refresh)


def _refresh_journal(refresh: Optional[callable]) -> None:
    """Trigger UI refresh when a journal update occurs."""
    if refresh:
        refresh()
