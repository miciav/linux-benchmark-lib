"""Dashboard viewmodels for UI rendering (UI-agnostic)."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Iterable

from lb_controller.api import RunJournal, RunStatus, TaskState
from lb_app.viewmodels import run_viewmodels


@dataclass(frozen=True)
class DashboardRow:
    host: str
    workload: str
    intensity: str
    status: str
    progress: str
    current_action: str
    last_rep_time: str


@dataclass(frozen=True)
class DashboardStatusSummary:
    total: int
    completed: int
    running: int
    failed: int
    skipped: int
    pending: int


@dataclass(frozen=True)
class DashboardLogMetadata:
    title: str = "Log Stream"


@dataclass(frozen=True)
class DashboardSnapshot:
    run_id: str
    rows: list[DashboardRow]
    row_count: int
    plan_rows: list[list[str]]
    intensity_map: dict[str, str]
    status_summary: DashboardStatusSummary
    log_metadata: DashboardLogMetadata


class DashboardViewModel:
    """Build dashboard snapshots from mutable run state."""

    def __init__(self, plan: list[dict[str, Any]], journal: RunJournal) -> None:
        self._journal = journal
        self._plan_rows = run_viewmodels.plan_rows(plan)
        self._intensity_map = _build_intensity_map(plan)
        self._log_metadata = DashboardLogMetadata()

    @property
    def run_id(self) -> str:
        return self._journal.run_id

    def snapshot(self) -> DashboardSnapshot:
        rows = _build_journal_rows(self._journal, self._intensity_map)
        status_summary = _summarize_statuses(self._journal.tasks.values())
        return DashboardSnapshot(
            run_id=self._journal.run_id,
            rows=rows,
            row_count=len(rows),
            plan_rows=self._plan_rows,
            intensity_map=self._intensity_map,
            status_summary=status_summary,
            log_metadata=self._log_metadata,
        )


def build_dashboard_viewmodel(
    plan: list[dict[str, Any]], journal: RunJournal
) -> DashboardViewModel:
    return DashboardViewModel(plan, journal)


def event_status_line(
    event_source: str, last_event_ts: float | None, *, now: float | None = None
) -> tuple[str, str]:
    """Return (status, detail) for event freshness."""
    if last_event_ts is None:
        return "waiting", "waiting"
    now_ts = time.monotonic() if now is None else now
    age = now_ts - last_event_ts
    freshness = "just now" if age < 1.0 else f"{age:.1f}s ago"
    return "live", freshness


def _build_intensity_map(plan: Iterable[dict[str, Any]]) -> dict[str, str]:
    intensity: dict[str, str] = {}
    for row in plan:
        name = row.get("name")
        if not name:
            continue
        intensity[name] = str(row.get("intensity", "-"))
    return intensity


def _build_journal_rows(
    journal: RunJournal, intensity_map: dict[str, str]
) -> list[DashboardRow]:
    if not journal.tasks:
        return []
    target_reps = run_viewmodels.target_repetitions(journal)
    rows: list[DashboardRow] = []
    pairs = sorted({(task.host, task.workload) for task in journal.tasks.values()})
    for host, workload in pairs:
        tasks = {
            task.repetition: task
            for task in journal.tasks.values()
            if task.host == host and task.workload == workload
        }
        status, _ = run_viewmodels.summarize_progress(tasks, target_reps)
        started = sum(1 for task in tasks.values() if task.status != RunStatus.PENDING)
        total = target_reps if target_reps > 0 else (len(tasks) or 1)
        progress = f"{started}/{total}"
        current_action = _current_action(tasks.values())
        last_duration = _latest_duration(tasks.values())
        rows.append(
            DashboardRow(
                host=host,
                workload=workload,
                intensity=intensity_map.get(workload, "-"),
                status=status,
                progress=progress,
                current_action=current_action,
                last_rep_time=last_duration,
            )
        )
    return rows


def _current_action(tasks: Iterable[TaskState]) -> str:
    running = [task for task in tasks if task.status == RunStatus.RUNNING]
    if not running:
        return ""
    running.sort(key=lambda task: task.repetition)
    active = running[0]
    return active.current_action or "Running..."


def _latest_duration(tasks: Iterable[TaskState]) -> str:
    latest: TaskState | None = None
    for task in tasks:
        if task.finished_at:
            if latest is None or task.finished_at > (latest.finished_at or 0):
                latest = task
    if latest and latest.duration_seconds is not None:
        return f"{latest.duration_seconds:.1f}s"
    return ""


def _summarize_statuses(tasks: Iterable[TaskState]) -> DashboardStatusSummary:
    counts = {
        "total": 0,
        "completed": 0,
        "running": 0,
        "failed": 0,
        "skipped": 0,
        "pending": 0,
    }
    for task in tasks:
        counts["total"] += 1
        if task.status == RunStatus.COMPLETED:
            counts["completed"] += 1
        elif task.status == RunStatus.RUNNING:
            counts["running"] += 1
        elif task.status == RunStatus.FAILED:
            counts["failed"] += 1
        elif task.status == RunStatus.SKIPPED:
            counts["skipped"] += 1
        else:
            counts["pending"] += 1
    return DashboardStatusSummary(**counts)
