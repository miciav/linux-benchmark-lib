"""View-model helpers for run plans and journals (UI-agnostic)."""

from __future__ import annotations

from typing import Dict, Iterable

from lb_controller.api import RunJournal, RunStatus, TaskState


def target_repetitions(journal: RunJournal) -> int:
    from_metadata = journal.metadata.get("repetitions")
    if isinstance(from_metadata, int) and from_metadata > 0:
        return from_metadata
    reps = [task.repetition for task in journal.tasks.values()]
    return max(reps) if reps else 0


def summarize_progress(
    tasks: Dict[int, TaskState], target_reps: int
) -> tuple[str, str]:
    total = target_reps or len(tasks)
    completed = sum(
        1
        for task in tasks.values()
        if task.status in (RunStatus.COMPLETED, RunStatus.SKIPPED, RunStatus.FAILED)
    )
    flags = _progress_flags(tasks)
    status = _status_from_flags(flags, completed, total)
    progress = _progress_label(completed, total)
    return status, progress


def journal_rows(journal: RunJournal) -> tuple[list[str], list[list[str]]]:
    """Return headers and rows summarizing a journal."""
    if not journal.tasks:
        return ["Host", "Workload"], []

    target = target_repetitions(journal)
    columns = ["Host", "Workload", "Run", "Last Action"]

    pairs = sorted({(task.host, task.workload) for task in journal.tasks.values()})
    rows: list[list[str]] = []
    for host, workload in pairs:
        tasks = {
            task.repetition: task
            for task in journal.tasks.values()
            if task.host == host and task.workload == workload
        }
        last_action = ""
        if tasks:
            latest = max(tasks.values(), key=lambda t: t.timestamp)
            last_action = latest.error or latest.current_action or ""

        status, progress = summarize_progress(tasks, target)
        row = [host, workload, f"{status}\n{progress}", last_action]
        rows.append(row)

    return columns, rows


def plan_rows(plan: Iterable[dict]) -> list[list[str]]:
    """Transform plan entries into table rows."""
    return [
        [
            item.get("name"),
            item.get("plugin"),
            item.get("intensity"),
            item.get("details"),
            item.get("repetitions", ""),
            item.get("status"),
        ]
        for item in plan
    ]


def _progress_flags(tasks: Dict[int, TaskState]) -> dict[str, bool]:
    return {
        "running": any(task.status == RunStatus.RUNNING for task in tasks.values()),
        "failed": any(task.status == RunStatus.FAILED for task in tasks.values()),
        "skipped": bool(tasks)
        and all(task.status == RunStatus.SKIPPED for task in tasks.values()),
    }


def _status_from_flags(
    flags: dict[str, bool], completed: int, total: int
) -> str:
    conditions = (
        (flags["failed"], "failed"),
        (flags["running"], "running"),
        (flags["skipped"], "skipped"),
        (total and completed >= total, "done"),
        (completed > 0, "partial"),
    )
    return next((label for cond, label in conditions if cond), "pending")


def _progress_label(completed: int, total: int) -> str:
    return f"{completed}/{total}" if total else "0/0"
