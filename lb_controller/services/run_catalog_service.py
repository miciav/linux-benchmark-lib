"""Service for listing and inspecting completed benchmark runs.

Runs are stored under `benchmark_results/<run_id>/` (or configured output dir).
This service provides a stable way for UI/CLI to discover available runs.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, cast

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
        for run_id in self._iter_run_ids():
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
            hosts, workloads = self._fallback_layout_metadata(output_root)
        elif not workloads:
            workloads = self._fallback_remote_workloads(output_root, hosts)

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
        return None

    @staticmethod
    def _load_journal(journal_path: Path) -> Dict[str, Any]:
        if not journal_path.exists():
            return {}
        try:
            parsed = json.loads(journal_path.read_text())
        except Exception:
            return {}
        if isinstance(parsed, dict):
            return cast(Dict[str, Any], parsed)
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
        tasks = _task_list(journal_data)
        hosts = {host for host in _task_field(tasks, "host") if isinstance(host, str)}
        workloads = {
            workload
            for workload in _task_field(tasks, "workload")
            if isinstance(workload, str)
        }
        return hosts, workloads

    @classmethod
    def _fallback_layout_metadata(cls, output_root: Path) -> tuple[Set[str], Set[str]]:
        entries = cls._candidate_dirs(output_root)
        if not entries:
            return set(), set()

        local_workloads = {
            entry.name for entry in entries if cls._looks_like_workload_dir(entry)
        }
        if local_workloads and len(local_workloads) == len(entries):
            return {"localhost"}, local_workloads

        remote_hosts = {entry.name for entry in entries if cls._looks_like_host_dir(entry)}
        if remote_hosts:
            return remote_hosts, cls._fallback_remote_workloads(output_root, remote_hosts)

        return set(), set()

    @classmethod
    def _fallback_remote_workloads(cls, output_root: Path, hosts: Set[str]) -> Set[str]:
        workloads: set[str] = set()
        for host in hosts:
            host_root = output_root / host
            if not host_root.exists():
                continue
            for entry in cls._candidate_dirs(host_root):
                if cls._looks_like_workload_dir(entry):
                    workloads.add(entry.name)
        return workloads

    @staticmethod
    def _candidate_dirs(root: Path) -> list[Path]:
        return [
            entry
            for entry in root.iterdir()
            if entry.is_dir() and not entry.name.startswith("_") and entry.name != "logs"
        ]

    @classmethod
    def _looks_like_host_dir(cls, root: Path) -> bool:
        children = cls._candidate_dirs(root)
        return any(cls._looks_like_workload_dir(child) for child in children)

    @staticmethod
    def _looks_like_workload_dir(root: Path) -> bool:
        has_children = False
        for entry in root.iterdir():
            has_children = True
            if entry.is_dir() and entry.name.startswith("rep"):
                return True
            if entry.is_file() and entry.name.endswith("_results.json"):
                return True
        return not has_children

    def _iter_run_ids(self) -> Iterable[str]:
        for item in self.output_dir.iterdir():
            if item.is_dir() and item.name.startswith("run-"):
                yield item.name


def _task_list(journal_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    tasks = journal_data.get("tasks") if isinstance(journal_data, dict) else None
    if not isinstance(tasks, list):
        return []
    return [task for task in tasks if isinstance(task, dict)]


def _task_field(tasks: Iterable[Dict[str, Any]], field: str) -> Iterable[Any]:
    return (task.get(field) for task in tasks)
