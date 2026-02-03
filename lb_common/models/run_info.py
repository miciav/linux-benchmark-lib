"""Shared run metadata used across layers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence


@dataclass(frozen=True)
class RunInfo:
    """Lightweight metadata about a benchmark run."""

    run_id: str
    output_root: Path
    report_root: Optional[Path]
    data_export_root: Optional[Path]
    hosts: Sequence[str]
    workloads: Sequence[str]
    created_at: Optional[datetime]
    journal_path: Optional[Path]
