"""Shared helpers for applying platform defaults."""

from __future__ import annotations

from lb_controller.api import BenchmarkConfig, PlatformConfig


def apply_platform_defaults(cfg: BenchmarkConfig, platform_config: PlatformConfig) -> None:
    """Apply platform defaults without mutating workload selection."""
    if platform_config.output_dir:
        cfg.output_dir = platform_config.output_dir
    if platform_config.report_dir:
        cfg.report_dir = platform_config.report_dir
    if platform_config.data_export_dir:
        cfg.data_export_dir = platform_config.data_export_dir
    if platform_config.loki:
        cfg.loki = platform_config.loki
