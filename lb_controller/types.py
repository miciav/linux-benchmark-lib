"""Shared controller data types and protocols."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

from lb_controller.controller_state import ControllerState

from lb_runner.benchmark_config import RemoteHostConfig


@dataclass
class InventorySpec:
    """Inventory specification for Ansible execution."""

    hosts: List[RemoteHostConfig]
    inventory_path: Optional[Path] = None


@dataclass
class ExecutionResult:
    """Result of a single Ansible playbook execution."""

    rc: int
    status: str
    stats: Dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        """Return True when the playbook completed successfully."""
        return self.rc == 0


@dataclass
class RunExecutionSummary:
    """Summary of a complete controller run."""

    run_id: str
    per_host_output: Dict[str, Path]
    phases: Dict[str, ExecutionResult]
    success: bool
    output_root: Path
    report_root: Path
    data_export_root: Path
    controller_state: ControllerState | None = None
    cleanup_allowed: bool = False


class RemoteExecutor(Protocol):
    """Protocol for remote execution engines."""

    def run_playbook(
        self,
        playbook_path: Path,
        inventory: InventorySpec,
        extravars: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        limit_hosts: Optional[List[str]] = None,
        *,
        cancellable: bool = True,
    ) -> ExecutionResult:
        """Execute a playbook and return the result."""
        raise NotImplementedError
