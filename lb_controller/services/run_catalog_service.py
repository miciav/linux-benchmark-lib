"""Service for listing and inspecting completed benchmark runs.

Runs are stored under `benchmark_results/<run_id>/` (or configured output dir).
This service provides a stable way for UI/CLI to discover available runs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set


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


class RunCatalogService:
    """Discover run directories and their basic metadata."""

    def __init__(
        self,
        output_dir: Path,
        report_dir: Optional[Path] = None,
        data_export_dir: Optional[Path] = None,
    ) -> None:
        self.output_dir = output_dir.resolve()
        self.report_dir = report_dir.resolve() if report_dir else None
        self.data_export_dir = data_export_dir.resolve() if data_export_dir else None

    def list_runs(self) -> List[RunInfo]:
        """Return all runs found under output_dir, newest first when possible."""
        if not self.output_dir.exists():
            return []

        runs: List[RunInfo] = []
        for item in self.output_dir.iterdir():
            if not item.is_dir():
                continue
            run_id = item.name
            if not run_id.startswith("run-"):
                continue
            info = self.get_run(run_id)
            if info:
                runs.append(info)

        runs.sort(
            key=lambda r: r.created_at.timestamp() if r.created_at else 0.0,
            reverse=True,
        )
        return runs

    def get_run(self, run_id: str) -> Optional[RunInfo]:
        """Return RunInfo for the given run_id if present."""
        output_root = (self.output_dir / run_id).resolve()
        if not output_root.exists():
            return None

        report_root = (
            (self.report_dir / run_id).resolve() if self.report_dir else None
        )
        export_root = (
            (self.data_export_dir / run_id).resolve() if self.data_export_dir else None
        )

        journal_path = output_root / "run_journal.json"
        journal_data: Dict[str, Any] = {}
        created_at: Optional[datetime] = None
        hosts: Set[str] = set()
        workloads: Set[str] = set()

        if journal_path.exists():
            try:
                journal_data = json.loads(journal_path.read_text())
            except Exception:
                journal_data = {}

        # Prefer metadata when present.
        metadata = journal_data.get("metadata", {}) if isinstance(journal_data, dict) else {}
        created_raw = metadata.get("created_at")
        if isinstance(created_raw, str):
            try:
                created_at = datetime.fromisoformat(created_raw)
            except Exception:
                created_at = None

        tasks = journal_data.get("tasks") if isinstance(journal_data, dict) else None
        if isinstance(tasks, list):
            for t in tasks:
                if not isinstance(t, dict):
                    continue
                host = t.get("host")
                workload = t.get("workload")
                if isinstance(host, str):
                    hosts.add(host)
                if isinstance(workload, str):
                    workloads.add(workload)

        if not hosts:
            # Fallback to directory names under output_root
            for host_dir in output_root.iterdir():
                if host_dir.is_dir():
                    hosts.add(host_dir.name)

        if not workloads and hosts:
            # Infer workloads by scanning first host folder.
            first_host = next(iter(hosts))
            host_root = output_root / first_host
            if host_root.exists():
                for wdir in host_root.iterdir():
                    if wdir.is_dir() and not wdir.name.startswith("_"):
                        workloads.add(wdir.name)

        return RunInfo(
            run_id=run_id,
            output_root=output_root,
            report_root=report_root if report_root and report_root.exists() else report_root,
            data_export_root=export_root if export_root and export_root.exists() else export_root,
            hosts=sorted(hosts),
            workloads=sorted(workloads),
            created_at=created_at,
            journal_path=journal_path if journal_path.exists() else None,
        )

