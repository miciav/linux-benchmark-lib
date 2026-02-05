import json
import hashlib
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any, Iterable
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from lb_runner.api import BenchmarkConfig, RunEvent


class RunStatus:
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


@dataclass
class TaskState:
    """
    Represents a single atomic unit of work (Host + Workload + Repetition).
    """

    host: str
    workload: str
    repetition: int
    status: str = RunStatus.PENDING
    current_action: str = ""
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())
    error: Optional[str] = None
    error_type: Optional[str] = None
    error_context: Optional[Dict[str, Any]] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    duration_seconds: Optional[float] = None

    @property
    def key(self) -> str:
        return f"{self.host}::{self.workload}::{self.repetition}"


@dataclass
class RunJournal:
    """
    Contains the entire execution plan and state.
    """

    run_id: str
    tasks: Dict[str, TaskState] = field(default_factory=dict)
    metadata: Dict = field(default_factory=dict)

    @classmethod
    def initialize(
        cls, run_id: str, config: Any, test_types: List[str]
    ) -> "RunJournal":
        """Factory to create a new journal based on configuration."""
        journal = cls(run_id=run_id)
        journal.metadata = _build_metadata(config)
        _populate_tasks(journal, config, test_types)
        return journal

    def add_task(self, task: TaskState) -> None:
        self.tasks[task.key] = task

    def get_tasks_by_host(self, host: str) -> List[TaskState]:
        return sorted(
            [t for t in self.tasks.values() if t.host == host],
            key=lambda x: x.repetition,
        )

    def get_task(self, host: str, workload: str, rep: int) -> Optional[TaskState]:
        """Return a specific task or None when absent."""
        key = f"{host}::{workload}::{rep}"
        return self.tasks.get(key)

    def update_task(
        self,
        host: str,
        workload: str,
        rep: int,
        status: str,
        action: str = "",
        error: Optional[str] = None,
        error_type: Optional[str] = None,
        error_context: Optional[Dict[str, Any]] = None,
    ) -> None:
        task = self.get_task(host, workload, rep)
        if not task:
            return
        now_ts = datetime.now().timestamp()
        self._update_task_timings(task, status, now_ts)
        task.status = status
        task.timestamp = now_ts
        if action:
            task.current_action = action
        if error:
            task.error = error
        if error_type:
            task.error_type = error_type
        if error_context:
            task.error_context = error_context

    def should_run(
        self,
        host: str,
        workload: str,
        rep: int,
        *,
        allow_skipped: bool = False,
    ) -> bool:
        """
        Determines if a task should be executed.
        Returns True if task is PENDING or FAILED (and we want to retry).
        For now, we skip COMPLETED tasks.
        """
        task = self.get_task(host, workload, rep)
        if task:
            if allow_skipped:
                return task.status != RunStatus.COMPLETED
            return task.status not in (RunStatus.COMPLETED, RunStatus.SKIPPED)
        # If task not found, it's technically new, so run it (this shouldn't
        # happen if initialized correctly).
        return True

    @staticmethod
    def _update_task_timings(task: TaskState, status: str, now_ts: float) -> None:
        if status == RunStatus.RUNNING and task.started_at is None:
            task.started_at = now_ts
        if status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.SKIPPED):
            task.finished_at = now_ts
            if task.started_at is not None:
                task.duration_seconds = max(0.0, task.finished_at - task.started_at)

    def save(self, path: Path) -> None:
        """Persist journal to disk."""
        data = asdict(self)
        # Ensure path exists
        if isinstance(path, str):
            path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        serialized = data.copy()
        serialized["tasks"] = [asdict(task) for task in self.tasks.values()]

        with open(path, "w") as f:
            json.dump(serialized, f, indent=2, default=str)

    @classmethod
    def load(cls, path: Path, config: Any | None = None) -> "RunJournal":
        """Load journal from disk, optionally validating against a config."""
        with open(path, "r") as f:
            data = json.load(f)

        metadata = data.get("metadata", {}) or {}
        _validate_config(metadata, config)
        tasks_data = data.pop("tasks", [])
        journal = cls(**data)
        journal.tasks = _load_tasks(tasks_data)
        if not getattr(journal, "metadata", None):
            journal.metadata = metadata
        return journal

    def rehydrate_config(self) -> BenchmarkConfig | None:
        """
        Return a BenchmarkConfig reconstructed from the stored config_dump.
        """
        cfg_dump = (self.metadata or {}).get("config_dump")
        if not cfg_dump:
            return None
        try:
            return BenchmarkConfig.model_validate(cfg_dump)
        except Exception:
            return None


class LogSink:
    """Persist events and mirror them to the run journal and optional log file."""

    def __init__(
        self, journal: RunJournal, journal_path: Path, log_file: Path | None = None
    ):
        self.journal = journal
        self.journal_path = journal_path
        self.log_file = log_file
        self._log_handle = None
        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            self._log_handle = log_file.open("a", encoding="utf-8")

    def emit(self, event: RunEvent) -> None:
        """Handle a single event."""
        self._update_journal(event)
        self._write_log(event)

    def emit_many(self, events: Iterable[RunEvent]) -> None:
        for ev in events:
            self.emit(ev)

    def close(self) -> None:
        if self._log_handle:
            try:
                self._log_handle.close()
            except Exception:
                pass
            self._log_handle = None

    def _update_journal(self, event: RunEvent) -> None:
        """Update journal tasks based on event state."""
        status_map = {
            "running": RunStatus.RUNNING,
            "done": RunStatus.COMPLETED,
            "failed": RunStatus.FAILED,
            "skipped": RunStatus.SKIPPED,
        }
        mapped = status_map.get(event.status.lower(), RunStatus.RUNNING)
        self.journal.update_task(
            event.host,
            event.workload,
            event.repetition,
            mapped,
            action="run_progress",
            error=event.message if mapped == RunStatus.FAILED else None,
            error_type=event.error_type if mapped == RunStatus.FAILED else None,
            error_context=event.error_context if mapped == RunStatus.FAILED else None,
        )
        self.journal.save(self.journal_path)

    def _write_log(self, event: RunEvent) -> None:
        """Append a single-line representation to the optional log file."""
        if not self._log_handle:
            return
        line = _build_log_line(event)
        try:
            self._log_handle.write(line + "\n")
            self._log_handle.flush()
        except Exception:
            pass


def _config_dump(config: Any) -> Dict[str, Any]:
    """Return a JSON-friendly dump of the config."""
    try:
        if hasattr(config, "model_dump"):
            return config.model_dump(mode="json")
    except Exception:
        pass
    try:
        return json.loads(json.dumps(config, default=str))
    except Exception:
        return {}


def _config_hash(cfg_dump: Dict[str, Any]) -> str:
    """Stable hash for config dumps."""
    try:
        payload = json.dumps(cfg_dump, sort_keys=True, default=str).encode("utf-8")
    except Exception:
        payload = str(cfg_dump).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _build_metadata(config: Any) -> Dict[str, Any]:
    cfg_dump = _config_dump(config)
    return {
        "created_at": datetime.now().isoformat(),
        "config_summary": str(config),
        "repetitions": getattr(config, "repetitions", None),
        "system_info": {},
        "config_dump": cfg_dump,
        "config_hash": _config_hash(cfg_dump),
    }


def _resolve_hosts(config: Any) -> List[Any]:
    return (
        config.remote_hosts
        if getattr(config, "remote_hosts", None)
        else [SimpleNamespace(name="localhost")]
    )


def _populate_tasks(journal: RunJournal, config: Any, test_types: List[str]) -> None:
    hosts = _resolve_hosts(config)
    for task in _iter_task_specs(config, test_types, hosts):
        journal.add_task(task)


def _iter_task_specs(
    config: Any, test_types: List[str], hosts: List[Any]
) -> Iterable[TaskState]:
    reps = range(1, config.repetitions + 1)
    return (
        TaskState(
            host=host.name,
            workload=test_name,
            repetition=rep,
            status=RunStatus.PENDING,
        )
        for test_name in _valid_test_names(config, test_types)
        for host in hosts
        for rep in reps
    )


def _valid_test_names(config: Any, test_types: List[str]) -> Iterable[str]:
    return (name for name in test_types if name in config.workloads)


def _validate_config(metadata: Dict[str, Any], config: Any | None) -> None:
    if config is None:
        return
    expected_reps = metadata.get("repetitions")
    if expected_reps and getattr(config, "repetitions", None) != expected_reps:
        raise ValueError("Config does not match journal repetitions; aborting resume.")
    cfg_dump = metadata.get("config_dump")
    cfg_hash = metadata.get("config_hash")
    if cfg_hash and cfg_dump:
        current_dump = _config_dump(config)
        current_hash = _config_hash(current_dump)
        if current_hash != cfg_hash:
            raise ValueError(
                "Config hash mismatch for resume; supply matching config or rely on "
                "journal config_dump."
            )


def _load_tasks(tasks_data: Iterable[Dict[str, Any]]) -> Dict[str, TaskState]:
    tasks: Dict[str, TaskState] = {}
    for task_data in tasks_data:
        task = TaskState(**task_data)
        tasks[task.key] = task
    return tasks


def _build_log_line(event: RunEvent) -> str:
    ts = datetime.fromtimestamp(
        event.timestamp or datetime.now().timestamp()
    ).isoformat()
    parts = [
        (
            f"[{ts}] {event.host} {event.workload} rep "
            f"{event.repetition}/{event.total_repetitions} status={event.status}"
        )
    ]
    if event.type and event.type != "status":
        parts.append(f" type={event.type}")
    if event.level and event.level != "INFO":
        parts.append(f" level={event.level}")
    if event.message:
        parts.append(f" msg={event.message}")
    if event.error_type:
        parts.append(f" err_type={event.error_type}")
    return "".join(parts)
