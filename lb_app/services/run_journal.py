"""Journal and resume helpers for run orchestration."""

from __future__ import annotations

from datetime import UTC, datetime
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
    run_identifier, journal_path = _resolve_resume_identifier(context)
    journal = _load_or_rebuild_journal(context, run_identifier, journal_path)

    rehydrate_resume_config(context, journal)
    ensure_resume_tasks(context, journal)
    _validate_run_id(run_id, journal.run_id)
    return journal, journal_path, journal.run_id


def _resolve_resume_identifier(context: RunContext) -> tuple[str, Path]:
    if context.resume_latest:
        return _latest_resume_identifier(context.config)
    if not context.resume_from:
        raise ValueError("Resume requested without a run identifier.")
    journal_path = context.config.output_dir / context.resume_from / "run_journal.json"
    return context.resume_from, journal_path


def _latest_resume_identifier(config: BenchmarkConfig) -> tuple[str, Path]:
    journal_path = find_latest_journal(config)
    if journal_path is not None:
        return journal_path.parent.name, journal_path
    latest = find_latest_results_run(config)
    if latest is None:
        raise ValueError("No previous run found to resume.")
    return latest


def _load_or_rebuild_journal(
    context: RunContext, run_identifier: str, journal_path: Path
) -> RunJournal:
    if journal_path.exists():
        return RunJournal.load(journal_path)
    run_root = journal_path.parent
    if not results_exist_for_run(run_root):
        raise ValueError(
            "Resume journal missing and no results were found to rebuild it."
        )
    journal = build_journal_from_results(run_identifier, context)
    run_root.mkdir(parents=True, exist_ok=True)
    journal.save(journal_path)
    return journal


def _validate_run_id(requested: str | None, actual: str) -> None:
    if requested and requested != actual:
        raise ValueError(f"Run ID mismatch: resume journal={actual}, cli={requested}")


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
    context.config = _select_rehydrated_config(
        context.config, rehydrated, meta_hash, cfg_hash
    )
    _restore_remote_execution(original_remote_exec, context.config)


def _select_rehydrated_config(
    current: BenchmarkConfig | None,
    rehydrated: BenchmarkConfig | None,
    meta_hash: str | None,
    cfg_hash: str | None,
) -> BenchmarkConfig | None:
    if rehydrated is None:
        return current
    if meta_hash and meta_hash != cfg_hash:
        return rehydrated
    if current is None:
        return rehydrated
    return current


def _restore_remote_execution(
    original_remote_exec: Any, config: BenchmarkConfig | None
) -> None:
    if not original_remote_exec or not config:
        return
    config.remote_execution.run_setup = original_remote_exec.run_setup
    config.remote_execution.run_teardown = original_remote_exec.run_teardown
    config.remote_execution.run_collect = original_remote_exec.run_collect


def ensure_resume_tasks(context: RunContext, journal: RunJournal) -> None:
    """Add any missing tasks to the resume journal for new hosts/workloads."""
    hosts = _resume_hosts(context)
    for host in hosts:
        _ensure_host_tasks(context, journal, host)


def _resume_hosts(context: RunContext) -> list[SimpleNamespace]:
    if getattr(context.config, "remote_hosts", None):
        return list(context.config.remote_hosts)
    return [SimpleNamespace(name="localhost")]


def _ensure_host_tasks(
    context: RunContext, journal: RunJournal, host: SimpleNamespace
) -> None:
    for test_name in context.target_tests:
        _ensure_test_tasks(context, journal, host, test_name)


def _ensure_test_tasks(
    context: RunContext, journal: RunJournal, host: SimpleNamespace, test_name: str
) -> None:
    if test_name not in context.config.workloads:
        return
    for rep in range(1, context.config.repetitions + 1):
        if journal.get_task(host.name, test_name, rep):
            continue
        journal.add_task(TaskState(host=host.name, workload=test_name, repetition=rep))


def initialize_new_journal(
    context: RunContext, run_id: str | None
) -> tuple[RunJournal, Path, str]:
    """Create a fresh journal for a new run."""
    run_identifier = run_id or generate_run_id()
    journal_path = context.config.output_dir / run_identifier / "run_journal.json"
    journal = RunJournal.initialize(
        run_identifier, context.config, context.target_tests
    )
    return journal, journal_path, run_identifier


def build_journal_from_results(
    run_id: str,
    context: RunContext,
    host_names: list[str] | None = None,
) -> RunJournal:
    """Construct a RunJournal from existing *_results.json artifacts."""
    journal = RunJournal.initialize(run_id, context.config, context.target_tests)
    output_root = context.config.output_dir / run_id
    hosts = host_names or _resolve_host_names(context)
    for host_name in hosts:
        _apply_host_results(journal, output_root, host_name, context)
    return journal


def _apply_host_results(
    journal: RunJournal,
    output_root: Path,
    host_name: str,
    context: RunContext,
) -> None:
    host_root = output_root / host_name
    if not host_root.exists():
        host_root = output_root
    for test_name in context.target_tests:
        _apply_test_results(journal, host_root, host_name, test_name)


def _apply_test_results(
    journal: RunJournal,
    host_root: Path,
    host_name: str,
    test_name: str,
) -> None:
    results_file = find_results_file(host_root, test_name)
    if not results_file:
        return
    entries = load_results_entries(results_file)
    for entry in entries:
        apply_result_entry(journal, host_name, test_name, entry)


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
    entry_error_type = entry.get("error_type")
    entry_error_context = entry.get("error_context")
    if gen_error or (gen_rc not in (None, 0)):
        journal.update_task(
            host_name,
            test_name,
            rep,
            RunStatus.FAILED,
            action="container_run",
            error=entry.get("error") or gen_error or f"returncode={gen_rc}",
            error_type=entry_error_type,
            error_context=entry_error_context,
        )
        return
    if entry_error_type:
        journal.update_task(
            host_name,
            test_name,
            rep,
            RunStatus.FAILED,
            action="container_run",
            error=entry.get("error") or "error recorded",
            error_type=entry_error_type,
            error_context=entry_error_context,
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
    candidates.sort(key=_journal_sort_key, reverse=True)
    return candidates[0]


def find_latest_results_run(config: BenchmarkConfig) -> tuple[str, Path] | None:
    """Return the most recent run directory that contains results files."""
    root = config.output_dir
    if not root.exists():
        return None
    latest = _latest_results_dir(root)
    if latest is None:
        return None
    return latest.name, latest / "run_journal.json"


def _latest_results_dir(root: Path) -> Path | None:
    latest: tuple[float, Path] | None = None
    for child in root.iterdir():
        candidate = _latest_results_candidate(child)
        if candidate is None:
            continue
        if latest is None or candidate[0] > latest[0]:
            latest = candidate
    if latest is None:
        return None
    return latest[1]


def _latest_results_candidate(path: Path) -> tuple[float, Path] | None:
    if not path.is_dir():
        return None
    mtime = _latest_results_mtime(path)
    if mtime is None:
        return None
    return mtime, path


def results_exist_for_run(run_root: Path) -> bool:
    """Return True when any *_results.json exists under the run root."""
    try:
        next(run_root.rglob("*_results.json"))
        return True
    except StopIteration:
        return False


def _resolve_host_names(context: RunContext) -> list[str]:
    hosts = (
        context.config.remote_hosts
        if getattr(context.config, "remote_hosts", None)
        else [SimpleNamespace(name="localhost")]
    )
    return [host.name for host in hosts]


def _latest_results_mtime(run_root: Path) -> float | None:
    latest: float | None = None
    for path in run_root.rglob("*_results.json"):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if latest is None or mtime > latest:
            latest = mtime
    return latest


def _journal_sort_key(path: Path) -> float:
    run_id = path.parent.name
    ts = _parse_run_id(run_id)
    if ts is not None:
        return ts.timestamp()
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _parse_run_id(run_id: str) -> datetime | None:
    if not run_id.startswith("run-"):
        return None
    try:
        return datetime.strptime(run_id[4:], "%Y%m%d-%H%M%S")
    except ValueError:
        return None


def generate_run_id() -> str:
    """Generate a timestamped run id matching the controller's format."""
    return datetime.now(UTC).strftime("run-%Y%m%d-%H%M%S")
