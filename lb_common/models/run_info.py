"""Shared run metadata used across layers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class RunInfo:
    """Lightweight metadata about a benchmark run."""

    run_id: str
    output_root: Path
    report_root: Path | None
    data_export_root: Path | None
    hosts: Sequence[str]
    workloads: Sequence[str]
    created_at: datetime | None
    journal_path: Path | None
