"""Service for listing and inspecting completed benchmark runs.

Runs are stored under `benchmark_results/<run_id>/` (or configured output dir).
This service provides a stable way for UI/CLI to discover available runs.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set

from lb_common.api import RunInfo


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
        output_root = self._resolve_output_root(run_id)
        if output_root is None:
            return None

        report_root = self._resolve_optional_root(self.report_dir, run_id)
        export_root = self._resolve_optional_root(self.data_export_dir, run_id)

        journal_path = output_root / "run_journal.json"
        journal_data = self._load_journal(journal_path)
        created_at = self._extract_created_at(journal_data)
        hosts, workloads = self._extract_hosts_workloads(journal_data)

        if not hosts:
            hosts = self._fallback_hosts(output_root)
        if not workloads and hosts:
            workloads = self._fallback_workloads(output_root, hosts)

        return RunInfo(
            run_id=run_id,
            output_root=output_root,
            report_root=self._existing_or_none(report_root),
            data_export_root=self._existing_or_none(export_root),
            hosts=sorted(hosts),
            workloads=sorted(workloads),
            created_at=created_at,
            journal_path=journal_path if journal_path.exists() else None,
        )

    def _resolve_output_root(self, run_id: str) -> Optional[Path]:
        output_root = (self.output_dir / run_id).resolve()
        return output_root if output_root.exists() else None

    @staticmethod
    def _resolve_optional_root(root: Optional[Path], run_id: str) -> Optional[Path]:
        if not root:
            return None
        return (root / run_id).resolve()

    @staticmethod
    def _existing_or_none(root: Optional[Path]) -> Optional[Path]:
        if root and root.exists():
            return root
        return root

    @staticmethod
    def _load_journal(journal_path: Path) -> Dict[str, Any]:
        if not journal_path.exists():
            return {}
        try:
            return json.loads(journal_path.read_text())
        except Exception:
            return {}

    @staticmethod
    def _extract_created_at(journal_data: Dict[str, Any]) -> Optional[datetime]:
        metadata = (
            journal_data.get("metadata", {}) if isinstance(journal_data, dict) else {}
        )
        created_raw = metadata.get("created_at")
        if not isinstance(created_raw, str):
            return None
        try:
            return datetime.fromisoformat(created_raw)
        except Exception:
            return None

    @staticmethod
    def _extract_hosts_workloads(
        journal_data: Dict[str, Any],
    ) -> tuple[Set[str], Set[str]]:
        hosts: Set[str] = set()
        workloads: Set[str] = set()
        tasks = journal_data.get("tasks") if isinstance(journal_data, dict) else None
        if not isinstance(tasks, list):
            return hosts, workloads
        for task in tasks:
            if not isinstance(task, dict):
                continue
            host = task.get("host")
            workload = task.get("workload")
            if isinstance(host, str):
                hosts.add(host)
            if isinstance(workload, str):
                workloads.add(workload)
        return hosts, workloads

    @staticmethod
    def _fallback_hosts(output_root: Path) -> Set[str]:
        return {entry.name for entry in output_root.iterdir() if entry.is_dir()}

    @staticmethod
    def _fallback_workloads(output_root: Path, hosts: Set[str]) -> Set[str]:
        first_host = next(iter(hosts))
        host_root = output_root / first_host
        if not host_root.exists():
            return set()
        return {
            entry.name
            for entry in host_root.iterdir()
            if entry.is_dir() and not entry.name.startswith("_")
        }
