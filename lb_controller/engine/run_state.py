"""Shared run state containers for controller helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lb_controller.models.types import InventorySpec
from lb_controller.services.journal import RunJournal


@dataclass
class RunState:
    """Internal container for a controller run."""

    resolved_run_id: str
    inventory: InventorySpec
    target_reps: int
    output_root: Path
    report_root: Path
    data_export_root: Path
    per_host_output: dict[str, Path]
    active_journal: RunJournal
    journal_file: Path
    extravars: dict[str, Any]
    test_types: list[str]


@dataclass
class RunFlags:
    """Mutable flags tracking stop/progress outcomes."""

    all_tests_success: bool = True
    stop_successful: bool = True
    stop_protocol_attempted: bool = False
