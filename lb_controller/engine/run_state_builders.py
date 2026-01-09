"""Builders for controller run state preparation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from lb_controller.models.types import InventorySpec
from lb_controller.services.journal import RunJournal
from lb_controller.services.paths import generate_run_id, prepare_per_host_dirs, prepare_run_dirs
from lb_runner.api import BenchmarkConfig


def resolve_run_id(run_id: str | None, journal: RunJournal | None) -> str:
    """Resolve the run id from journal, explicit input, or generate a new one."""
    return journal.run_id if journal is not None else run_id or generate_run_id()


def build_inventory(config: BenchmarkConfig) -> InventorySpec:
    """Build inventory spec from controller config."""
    return InventorySpec(
        hosts=config.remote_hosts,
        inventory_path=config.remote_execution.inventory_path,
    )


@dataclass(frozen=True)
class RunDirectoryPreparer:
    """Prepare output/report directories for a run."""

    config: BenchmarkConfig

    def prepare(
        self, run_id: str
    ) -> tuple[Path, Path, Path, dict[str, Path]]:
        output_root, report_root, data_export_root = prepare_run_dirs(
            self.config, run_id
        )
        per_host_output = prepare_per_host_dirs(
            self.config.remote_hosts,
            output_root=output_root,
            report_root=report_root,
        )
        return output_root, report_root, data_export_root, per_host_output


@dataclass(frozen=True)
class ExtravarsBuilder:
    """Assemble Ansible extravars for a controller run."""

    config: BenchmarkConfig

    def build(
        self,
        *,
        run_id: str,
        output_root: Path,
        report_root: Path,
        data_export_root: Path,
        per_host_output: dict[str, Path],
        target_reps: int,
        collector_packages: Iterable[str],
    ) -> dict[str, Any]:
        remote_output_root = f"/tmp/benchmark_results/{run_id}"
        return {
            "run_id": run_id,
            "output_root": str(output_root),
            "remote_output_root": remote_output_root,
            "report_root": str(report_root),
            "data_export_root": str(data_export_root),
            "lb_workdir": self.config.remote_execution.lb_workdir,
            "per_host_output": {k: str(v) for k, v in per_host_output.items()},
            "benchmark_config": self.config.model_dump(mode="json"),
            "use_container_fallback": self.config.remote_execution.use_container_fallback,
            "lb_upgrade_pip": self.config.remote_execution.upgrade_pip,
            "collector_apt_packages": sorted(collector_packages),
            "workload_runner_install_deps": False,
            "repetitions_total": target_reps,
            "repetition_index": 0,
        }
