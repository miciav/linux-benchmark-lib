"""Aggregation helpers for the dashboard UI."""

from __future__ import annotations

import time
from typing import Any, Dict, Iterable, List

try:
    from lb_app.api import RunJournal, RunStatus, TaskState
except ImportError:
    class RunStatus:
        RUNNING = "running"
        COMPLETED = "completed"
        FAILED = "failed"
        SKIPPED = "skipped"
        PENDING = "pending"

    TaskState = Any
    RunJournal = Any

from lb_ui.presenters import viewmodels


def build_intensity_map(plan_rows: List[Dict[str, str]]) -> Dict[str, str]:
    intensity: Dict[str, str] = {}
    for row in plan_rows:
        name = row.get("name")
        if not name:
            continue
        intensity[name] = row.get("intensity", "-")
    return intensity


def target_repetitions(journal: RunJournal) -> int:
    return viewmodels.target_repetitions(journal)


def unique_pairs(journal: RunJournal) -> Iterable[tuple[str, str]]:
    seen = set()
    for task in journal.tasks.values():
        key = (task.host, task.workload)
        if key in seen:
            continue
        seen.add(key)
        yield key


def tasks_for(journal: RunJournal, host: str, workload: str) -> Dict[int, TaskState]:
    return {
        task.repetition: task
        for task in journal.tasks.values()
        if task.host == host and task.workload == workload
    }


def summarize_status(tasks: Dict[int, TaskState], target_reps: int) -> str:
    status, _ = viewmodels.summarize_progress(tasks, target_reps)
    return status


def style_status(status: str) -> str:
    return {
        "failed": "[red]failed[/red]",
        "running": "[yellow]running[/yellow]",
        "skipped": "[dim]skipped[/dim]",
        "done": "[green]done[/green]",
        "partial": "[yellow]partial[/yellow]",
        "pending": "[dim]pending[/dim]",
    }.get(status, status)


def started_repetitions(tasks: Dict[int, TaskState]) -> int:
    return sum(1 for task in tasks.values() if task.status != RunStatus.PENDING)


def latest_duration(tasks: Dict[int, TaskState]) -> str:
    latest = None
    for task in tasks.values():
        if task.finished_at:
            if latest is None or task.finished_at > latest.finished_at:
                latest = task
    if latest and latest.duration_seconds is not None:
        return f"{latest.duration_seconds:.1f}s"
    return ""


def computed_journal_height(row_count: int, term_height: int) -> int:
    """Pick a journal height that leaves room for logs."""
    min_height = min(30, max(10, row_count + 5))
    log_min = 6
    available = max(10, term_height - log_min)
    return min(available, min_height)


def split_timing(line: str) -> tuple[str, str]:
    text = line.strip()
    if " done in " not in text:
        return line, ""
    message, timing = text.rsplit(" done in ", 1)
    if not timing.endswith("s"):
        return line, ""
    return message.rstrip(), timing


def event_status_line(event_source: str, last_event_ts: float | None) -> str:
    if last_event_ts is None:
        return "[dim]Event stream: waiting[/dim]"
    age = time.monotonic() - last_event_ts
    freshness = "just now" if age < 1.0 else f"{age:.1f}s ago"
    return f"[green]Event stream: live ({event_source}, {freshness})[/green]"
