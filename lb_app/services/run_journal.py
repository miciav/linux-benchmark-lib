"""Journal and resume helpers for run orchestration."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from lb_controller.api import BenchmarkConfig, workload_output_dir

from lb_controller.api import RunJournal, RunStatus, TaskState
from lb_app.services.run_config import hash_config
from lb_app.services.run_types import RunContext


def load_resume_journal(
    context: RunContext, run_id: str | None
) -> tuple[RunJournal, Path, str]:
    """Load an existing journal and reconcile configuration for resume."""
    journal_path = resolve_resume_path(context)
    journal = RunJournal.load(journal_path)
    rehydrate_resume_config(context, journal)
    ensure_resume_tasks(context, journal)
    if run_id and run_id != journal.run_id:
        raise ValueError(
            f"Run ID mismatch: resume journal={journal.run_id}, cli={run_id}"
        )
    return journal, journal_path, journal.run_id


def resolve_resume_path(context: RunContext) -> Path:
    """Locate the correct journal path for resume."""
    if context.resume_latest:
        journal_path = find_latest_journal(context.config)
        if journal_path is None:
            raise ValueError("No previous run found to resume.")
        return journal_path
    return context.config.output_dir / context.resume_from / "run_journal.json"


def rehydrate_resume_config(context: RunContext, journal: RunJournal) -> None:
    """Restore config from journal when resuming, preserving explicit overrides."""
    original_remote_exec = context.config.remote_execution if context.config else None
    rehydrated = journal.rehydrate_config()
    meta_hash = (journal.metadata or {}).get("config_hash")
    cfg_hash = hash_config(context.config)
    if meta_hash and meta_hash != cfg_hash and rehydrated is not None:
        context.config = rehydrated
    elif context.config is None and rehydrated is not None:
        context.config = rehydrated
    if original_remote_exec and context.config:
        context.config.remote_execution.run_setup = original_remote_exec.run_setup
        context.config.remote_execution.run_teardown = (
            original_remote_exec.run_teardown
        )
        context.config.remote_execution.run_collect = (
            original_remote_exec.run_collect
        )


def ensure_resume_tasks(context: RunContext, journal: RunJournal) -> None:
    """Add any missing tasks to the resume journal for new hosts/workloads."""
    hosts = (
        context.config.remote_hosts
        if getattr(context.config, "remote_hosts", None)
        else [SimpleNamespace(name="localhost")]
    )
    for test_name in context.target_tests:
        if test_name not in context.config.workloads:
            continue
        for host in hosts:
            for rep in range(1, context.config.repetitions + 1):
                if journal.get_task(host.name, test_name, rep):
                    continue
                journal.add_task(
                    TaskState(host=host.name, workload=test_name, repetition=rep)
                )


def initialize_new_journal(
    context: RunContext, run_id: str | None
) -> tuple[RunJournal, Path, str]:
    """Create a fresh journal for a new run."""
    run_identifier = run_id or generate_run_id()
    journal_path = context.config.output_dir / run_identifier / "run_journal.json"
    journal = RunJournal.initialize(run_identifier, context.config, context.target_tests)
    return journal, journal_path, run_identifier


def build_journal_from_results(
    run_id: str,
    context: RunContext,
    host_name: str,
) -> RunJournal:
    """Construct a RunJournal from existing *_results.json artifacts."""
    journal = RunJournal.initialize(run_id, context.config, context.target_tests)
    output_root = context.config.output_dir / run_id
    for test_name in context.target_tests:
        results_file = find_results_file(output_root, test_name)
        if not results_file:
            continue
        entries = load_results_entries(results_file)
        for entry in entries:
            apply_result_entry(journal, host_name, test_name, entry)
    return journal


def find_results_file(output_root: Path, test_name: str) -> Path | None:
    """Locate results JSON for a given workload."""
    workload_dir = workload_output_dir(output_root, test_name)
    candidates = [
        workload_dir / f"{test_name}_results.json",
        output_root / f"{test_name}_results.json",
    ]
    return next((path for path in candidates if path.exists()), None)


def load_results_entries(path: Path) -> list[dict[str, Any]]:
    """Load result entries from disk, tolerating errors."""
    try:
        loaded = json.loads(path.read_text())
        return loaded or []
    except Exception:
        return []


def apply_result_entry(
    journal: RunJournal,
    host_name: str,
    test_name: str,
    entry: dict[str, Any],
) -> None:
    """Update journal tasks from a single results entry."""
    rep = entry.get("repetition")
    if rep is None:
        return
    task = journal.get_task(host_name, test_name, rep)
    if not task:
        return
    populate_task_times(task, entry)
    update_task_status_from_result(journal, host_name, test_name, rep, entry)


def populate_task_times(task: TaskState, entry: dict[str, Any]) -> None:
    """Fill in start/end/duration fields from results."""
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


def update_task_status_from_result(
    journal: RunJournal,
    host_name: str,
    test_name: str,
    rep: int,
    entry: dict[str, Any],
) -> None:
    """Set task status based on generator result fields."""
    gen_result = entry.get("generator_result") or {}
    gen_error = gen_result.get("error")
    gen_rc = gen_result.get("returncode")
    if gen_error or (gen_rc not in (None, 0)):
        journal.update_task(
            host_name,
            test_name,
            rep,
            RunStatus.FAILED,
            action="container_run",
            error=gen_error or f"returncode={gen_rc}",
        )
        return
    journal.update_task(
        host_name,
        test_name,
        rep,
        RunStatus.COMPLETED,
        action="container_run",
    )


def find_latest_journal(config: BenchmarkConfig) -> Path | None:
    """Return the most recent journal path if present."""
    root = config.output_dir
    if not root.exists():
        return None
    candidates = []
    for child in root.iterdir():
        candidate = child / "run_journal.json"
        if candidate.exists():
            candidates.append(candidate)
    if not candidates:
        return None
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[0]


def generate_run_id() -> str:
    """Generate a timestamped run id matching the controller's format."""
    return datetime.utcnow().strftime("run-%Y%m%d-%H%M%S")
