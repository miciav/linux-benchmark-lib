"""Output and artifact helpers for the local runner."""

from __future__ import annotations

import logging
from pathlib import Path

from lb_runner import system_info
from lb_runner.system_info_io import write_outputs
from lb_runner.benchmark_config import BenchmarkConfig


def ensure_run_dirs(config: BenchmarkConfig, run_id: str) -> tuple[Path, Path, Path]:
    """Create required local output directories for a run."""
    config.ensure_output_dirs()

    def _scope_with_run_id(base: Path) -> Path:
        """
        Attach run_id unless the path is already scoped.

        Remote runs pass in an output_dir that already contains run_id; avoid
        nesting an extra level in that case so collectors and plugins write
        where the controller expects to fetch from.
        """
        if run_id in base.parts:
            return base.resolve()
        return (base / run_id).resolve()

    output_root = _scope_with_run_id(config.output_dir)
    report_root = _scope_with_run_id(config.report_dir)
    data_export_root = _scope_with_run_id(config.data_export_dir)
    
    # Only create output_root; report/export dirs are created on demand by analytics.
    output_root.mkdir(parents=True, exist_ok=True)
    
    return output_root, data_export_root, report_root


def workload_output_dir(output_root: Path, workload: str, ensure: bool = False) -> Path:
    """
    Return the output directory dedicated to a workload inside a run.

    Args:
        output_root: Base output directory for the run (already scoped by run_id/host).
        workload: Workload/plugin identifier.
        ensure: When True, create the directory.
    """
    path = output_root / workload
    if ensure:
        path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_runner_log(output_dir: Path, logger: logging.Logger) -> bool:
    """Attach a single runner.log file handler if one is not already present."""
    for handler in logger.handlers:
        if isinstance(handler, logging.FileHandler):
            return True
    try:
        log_path = output_dir / "runner.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        logger.addHandler(file_handler)
        return True
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Failed to attach file handler: %s", exc)
        return False


def write_system_info_artifacts(collected: system_info.SystemInfo, output_root: Path, logger: logging.Logger) -> None:
    """Persist system info JSON/CSV artifacts when an output directory is present."""
    json_path = output_root / "system_info.json"
    csv_path = output_root / "system_info.csv"
    try:
        write_outputs(collected, json_path, csv_path)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Failed to write system info artifacts: %s", exc)
