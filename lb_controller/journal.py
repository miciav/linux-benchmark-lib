import json
import hashlib
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any, Iterable
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from lb_runner.events import RunEvent
from lb_runner.benchmark_config import BenchmarkConfig

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
    def initialize(cls, run_id: str, config: Any, test_types: List[str]) -> 'RunJournal':
        """Factory to create a new journal based on configuration."""
        journal = cls(run_id=run_id)
        cfg_dump = _config_dump(config)
        journal.metadata = {
            "created_at": datetime.now().isoformat(),
            "config_summary": str(config),  # Simple representation
            "repetitions": getattr(config, "repetitions", None),
            "system_info": {},  # host -> summary string/path mapping
            "config_dump": cfg_dump,
            "config_hash": _config_hash(cfg_dump),
        }
        
        # Pre-populate tasks based on config
        # We iterate test_types order to keep logical sequence
        hosts = config.remote_hosts if getattr(config, "remote_hosts", None) else [SimpleNamespace(name="localhost")]
        for test_name in test_types:
            if test_name not in config.workloads:
                continue
                
            for host in hosts:
                for rep in range(1, config.repetitions + 1):
                    task = TaskState(
                        host=host.name,
                        workload=test_name,
                        repetition=rep,
                        status=RunStatus.PENDING
                    )
                    journal.add_task(task)
        return journal

    def add_task(self, task: TaskState) -> None:
        self.tasks[task.key] = task

    def get_tasks_by_host(self, host: str) -> List[TaskState]:
        return sorted([t for t in self.tasks.values() if t.host == host], key=lambda x: x.repetition)

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
    ) -> None:
        for t in self.tasks.values():
            if t.host == host and t.workload == workload and t.repetition == rep:
                now_ts = datetime.now().timestamp()
                if status == RunStatus.RUNNING and t.started_at is None:
                    t.started_at = now_ts
                if status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.SKIPPED):
                    t.finished_at = now_ts
                    if t.started_at is not None:
                        t.duration_seconds = max(0.0, t.finished_at - t.started_at)
                t.status = status
                t.timestamp = now_ts
                if action:
                    t.current_action = action
                if error:
                    t.error = error
                break

    def should_run(self, host: str, workload: str, rep: int) -> bool:
        """
        Determines if a task should be executed.
        Returns True if task is PENDING or FAILED (and we want to retry).
        For now, we skip COMPLETED tasks.
        """
        for t in self.tasks.values():
            if t.host == host and t.workload == workload and t.repetition == rep:
                return t.status not in (RunStatus.COMPLETED, RunStatus.SKIPPED)
        # If task not found, it's technically new, so run it (though this shouldn't happen if initialized correctly)
        return True

    def save(self, path: Path) -> None:
        """Persist journal to disk."""
        data = asdict(self)
        # Ensure path exists
        if isinstance(path, str):
            path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        serialized = data.copy()
        serialized["tasks"] = [asdict(task) for task in self.tasks.values()]

        with open(path, 'w') as f:
            json.dump(serialized, f, indent=2, default=str)

    @classmethod
    def load(cls, path: Path, config: Any | None = None) -> 'RunJournal':
        """Load journal from disk, optionally validating against a config."""
        with open(path, 'r') as f:
            data = json.load(f)

        metadata = data.get("metadata", {}) or {}
        cfg_dump = metadata.get("config_dump")
        cfg_hash = metadata.get("config_hash")

        if config is not None:
            expected_reps = metadata.get("repetitions")
            if expected_reps and getattr(config, "repetitions", None) != expected_reps:
                raise ValueError("Config does not match journal repetitions; aborting resume.")
            if cfg_hash and cfg_dump:
                current_dump = _config_dump(config)
                current_hash = _config_hash(current_dump)
                if current_hash != cfg_hash:
                    raise ValueError("Config hash mismatch for resume; supply matching config or rely on journal config_dump.")
        tasks_data = data.pop('tasks', [])
        journal = cls(**data)
        journal.tasks = {}
        for t in tasks_data:
            task = TaskState(**t)
            journal.tasks[task.key] = task
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
    """Persist events and mirror them to the run journal and optional stdout/log file."""

    def __init__(self, journal: RunJournal, journal_path: Path, log_file: Path | None = None):
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
        )
        self.journal.save(self.journal_path)

def _write_log(self, event: RunEvent) -> None:
        if not self._log_handle:
            return
        ts = datetime.fromtimestamp(event.timestamp or datetime.now().timestamp()).isoformat()
        line = f"[{ts}] {event.host} {event.workload} rep {event.repetition}/{event.total_repetitions} status={event.status}"
        if event.message:
            line += f" msg={event.message}"
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
