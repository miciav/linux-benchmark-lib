"""Helpers for run directory and identifier management."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Dict, Iterable

from lb_runner.api import BenchmarkConfig, RemoteHostConfig

# Controller-local Ansible playbook root
ANSIBLE_ROOT = Path(__file__).resolve().parent.parent / "ansible"
PLAYBOOK_FILES = {
    "setup_playbook": "setup.yml",
    "run_playbook": "run_benchmark.yml",
    "collect_playbook": "collect.yml",
    "teardown_playbook": "teardown.yml",
}


def generate_run_id() -> str:
    """Generate a monotonic timestamp-based run identifier."""
    return datetime.now(UTC).strftime("run-%Y%m%d-%H%M%S")


def prepare_run_dirs(
    config: BenchmarkConfig,
    run_id: str,
) -> tuple[Path, Path, Path]:
    """Create base directories for a run."""
    output_root = (config.output_dir / run_id).resolve()
    report_root = (config.report_dir / run_id).resolve()
    data_export_root = (config.data_export_dir / run_id).resolve()

    # Only create output_root; report/export dirs are created on demand by analytics.
    output_root.mkdir(parents=True, exist_ok=True)

    return output_root, report_root, data_export_root


def prepare_per_host_dirs(
    remote_hosts: Iterable[RemoteHostConfig],
    output_root: Path,
    report_root: Path,
) -> Dict[str, Path]:
    """Prepare output/report directories per host."""
    per_host: Dict[str, Path] = {}
    for host in remote_hosts:
        host_dir = output_root / host.name
        host_dir.mkdir(parents=True, exist_ok=True)
        per_host[host.name] = host_dir
    return per_host


def apply_playbook_defaults(config: BenchmarkConfig) -> None:
    """Ensure remote_execution playbook paths point to controller Ansible assets."""
    rex = config.remote_execution
    for attr, fname in PLAYBOOK_FILES.items():
        current = getattr(rex, attr)
        if current is not None and Path(current).exists():
            continue
        candidate = ANSIBLE_ROOT / "playbooks" / fname
        setattr(rex, attr, candidate)
