"""Output and artifact helpers for the local runner."""

from __future__ import annotations

import logging
from pathlib import Path

from lb_runner import system_info
from lb_runner.benchmark_config import BenchmarkConfig


def ensure_run_dirs(config: BenchmarkConfig, run_id: str) -> tuple[Path, Path, Path]:
    """Create required local output directories for a run."""
    config.ensure_output_dirs()
    output_root = (config.output_dir / run_id).resolve()
    report_root = (config.report_dir / run_id).resolve()
    data_export_root = (config.data_export_dir / run_id).resolve()
    for path in (output_root, report_root, data_export_root):
        path.mkdir(parents=True, exist_ok=True)
    return output_root, data_export_root, report_root


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
        system_info.write_outputs(collected, json_path, csv_path)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Failed to write system info artifacts: %s", exc)
