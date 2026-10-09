"""Shared run metadata used across layers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal


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
    experiment_id: str | None = None


@dataclass(frozen=True)
class ExperimentInfo:
    """A group of runs: same experiment_id, or every run of one folder."""

    id: str
    kind: Literal["experiment", "folder"]
    runs: Sequence[RunInfo]

    @property
    def hosts(self) -> list[str]:
        return sorted({host for run in self.runs for host in run.hosts})

    @property
    def workloads(self) -> list[str]:
        return sorted({w for run in self.runs for w in run.workloads})

    @property
    def first_created(self) -> datetime | None:
        stamps = [run.created_at for run in self.runs if run.created_at]
        return min(stamps) if stamps else None

    @property
    def last_created(self) -> datetime | None:
        stamps = [run.created_at for run in self.runs if run.created_at]
        return max(stamps) if stamps else None
