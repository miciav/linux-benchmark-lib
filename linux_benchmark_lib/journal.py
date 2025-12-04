import json
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
from datetime import datetime
from pathlib import Path

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
        journal.metadata = {
            "created_at": datetime.now().isoformat(),
            "config_summary": str(config),  # Simple representation
            "repetitions": getattr(config, "repetitions", None),
        }
        
        # Pre-populate tasks based on config
        # We iterate test_types order to keep logical sequence
        for test_name in test_types:
            if test_name not in config.workloads:
                continue
                
            # Assuming config.remote_hosts is available
            for host in config.remote_hosts:
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

        if config is not None:
            expected_reps = data.get("metadata", {}).get("repetitions")
            if expected_reps and getattr(config, "repetitions", None) != expected_reps:
                raise ValueError("Config does not match journal repetitions; aborting resume.")
        tasks_data = data.pop('tasks', [])
        journal = cls(**data)
        journal.tasks = {}
        for t in tasks_data:
            task = TaskState(**t)
            journal.tasks[task.key] = task
        return journal
