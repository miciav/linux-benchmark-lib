from dataclasses import dataclass, field
from typing import List, Optional, Dict
from datetime import datetime

@dataclass
class TaskState:
    """
    Represents a single atomic unit of work (Host + Workload + Repetition).
    """
    host: str
    workload: str
    repetition: int
    status: str = "PENDING"  # States: PENDING, RUNNING, COMPLETED, FAILED, SKIPPED
    current_action: str = "" # Detail of the current action (e.g., "Gathering Facts")
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())
    error: Optional[str] = None

    @property
    def key(self) -> str:
        """Unique key for this task."""
        return f"{self.host}::{self.workload}::{self.repetition}"

@dataclass
class RunJournal:
    """
    Contains the entire execution plan and state.
    Acting as the Single Source of Truth for the benchmark run.
    """
    run_id: str
    tasks: List[TaskState] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)

    def add_task(self, task: TaskState):
        self.tasks.append(task)

    def get_tasks_by_host(self, host: str) -> List[TaskState]:
        """Returns all tasks for a specific host, sorted by repetition."""
        return sorted([t for t in self.tasks if t.host == host], key=lambda x: x.repetition)

    def update_task(self, host: str, workload: str, rep: int, status: str, action: str = "", error: Optional[str] = None):
        """Helper to update the state of a specific task."""
        for t in self.tasks:
            if t.host == host and t.workload == workload and t.repetition == rep:
                t.status = status
                t.timestamp = datetime.now().timestamp()
                if action:
                    t.current_action = action
                if error:
                    t.error = error
                break
