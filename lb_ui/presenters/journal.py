"""Presenter for Run Journals."""

from __future__ import annotations


from typing import Dict, List, Tuple
from lb_controller.api import RunJournal, RunStatus, TaskState
from lb_ui.tui.system.models import TableModel


def _target_repetitions(journal: RunJournal) -> int:
    from_metadata = journal.metadata.get("repetitions")
    if isinstance(from_metadata, int) and from_metadata > 0:
        return from_metadata
    reps = [task.repetition for task in journal.tasks.values()]
    return max(reps) if reps else 0

def _summarize_progress(tasks: Dict[int, TaskState], target_reps: int) -> Tuple[str, str]:
    total = target_reps or len(tasks)
    completed = sum(
        1
        for task in tasks.values()
        if task.status in (RunStatus.COMPLETED, RunStatus.SKIPPED, RunStatus.FAILED)
    )
    running = any(task.status == RunStatus.RUNNING for task in tasks.values())
    failed = any(task.status == RunStatus.FAILED for task in tasks.values())
    skipped = tasks and all(task.status == RunStatus.SKIPPED for task in tasks.values())

    if failed:
        status = "failed"
    elif running:
        status = "running"
    elif skipped:
        status = "skipped"
    elif total and completed >= total:
        status = "done"
    elif completed > 0:
        status = "partial"
    else:
        status = "pending"

    progress = f"{completed}/{total}" if total else "0/0"
    return status, progress


def build_journal_summary(journal: RunJournal) -> tuple[list[str], list[list[str]]]:
    """
    Summarize run progress by host/workload collapsing repetitions.

    Returns column headers and row data for a compact table (without TableModel).
    """
    columns = ["Host", "Workload", "Run", "Last Action"]
    if not journal.tasks:
        return columns, []

    target = _target_repetitions(journal)
    rows: list[list[str]] = []
    pairs = sorted({(task.host, task.workload) for task in journal.tasks.values()})

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

        status, progress = _summarize_progress(tasks, target)
        rows.append([host, workload, f"{status}\n{progress}", last_action])

    return columns, rows

def build_journal_table(journal: RunJournal) -> TableModel:
    """Transform a RunJournal into a TableModel."""
    if not journal.tasks:
        return TableModel(
            title=f"Run Journal (ID: {journal.run_id})",
            columns=["Host", "Workload"],
            rows=[]
        )

    target = _target_repetitions(journal)
    columns = ["Host", "Workload", "Run", "Last Action"]

    pairs = sorted({(task.host, task.workload) for task in journal.tasks.values()})
    rows: List[List[str]] = []
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

        status, progress = _summarize_progress(tasks, target)
        row = [host, workload, f"{status}\n{progress}", last_action]
        rows.append(row)

    return TableModel(
        title=f"Run Journal (ID: {journal.run_id})",
        columns=columns,
        rows=rows,
    )
