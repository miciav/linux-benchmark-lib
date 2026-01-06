"""Helpers for workload selection and run planning."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from lb_runner.models.config import WorkloadConfig
from lb_plugins.api import WorkloadIntensity, WorkloadPlugin


logger = logging.getLogger(__name__)


def generate_run_id() -> str:
    """Generate a timestamp-based run id."""
    return datetime.now(UTC).strftime("run-%Y%m%d-%H%M%S")


def select_repetitions(
    total_repetitions: int,
    repetition_override: int | None,
    pending_reps: list[int] | None,
) -> list[int]:
    if pending_reps:
        reps = pending_reps
    elif repetition_override is not None:
        reps = [repetition_override]
    else:
        reps = list(range(1, total_repetitions + 1))
    for rep in reps:
        if rep is None or rep <= 0:
            raise ValueError("Repetition index must be a positive integer")
    return reps


def resolve_workload(name: str, workloads: dict[str, WorkloadConfig]) -> WorkloadConfig:
    """Return the workload configuration for the given name."""
    workload = workloads.get(name)
    if workload is None:
        raise ValueError(f"Unknown workload: {name}")
    return workload


def resolve_config_input(
    workload_cfg: WorkloadConfig,
    plugin: WorkloadPlugin,
    logger: logging.Logger,
    plugin_settings: dict[str, Any] | None = None,
) -> Any:
    # Start with global plugin settings as base
    base_settings = {}
    if plugin_settings:
        base_settings = plugin_settings.get(workload_cfg.plugin, {}).copy()

    # Workload-specific options override global settings
    user_options = workload_cfg.options
    
    # Merge strategy: shallow merge is usually sufficient for config dicts here
    config_input = {**base_settings, **user_options}

    if workload_cfg.intensity and workload_cfg.intensity != "user_defined":
        try:
            level = WorkloadIntensity(workload_cfg.intensity)
            preset_config = plugin.get_preset_config(level)
            if preset_config:
                logger.info("Using preset configuration for intensity '%s'", level.value)
                return preset_config
            logger.warning(
                "Plugin '%s' does not support intensity '%s', falling back to user options.",
                plugin.name,
                level.value,
            )
        except ValueError:
            logger.warning(
                "Invalid intensity level '%s', falling back to user options.",
                workload_cfg.intensity,
            )
    return config_input


class RunPlanner:
    """Provide run planning helpers bound to a configuration snapshot."""

    def __init__(
        self,
        workloads: dict[str, WorkloadConfig],
        repetitions: int,
        logger: logging.Logger,
        plugin_settings: dict[str, Any] | None = None,
    ) -> None:
        self._workloads = workloads
        self._repetitions = repetitions
        self._logger = logger
        self._plugin_settings = plugin_settings or {}

    def generate_run_id(self) -> str:
        return generate_run_id()

    def select_repetitions(
        self, repetition_override: int | None, pending_reps: list[int] | None
    ) -> list[int]:
        return select_repetitions(
            self._repetitions, repetition_override, pending_reps
        )

    def resolve_workload(self, name: str) -> WorkloadConfig:
        return resolve_workload(name, self._workloads)

    def resolve_config_input(
        self, workload_cfg: WorkloadConfig, plugin: WorkloadPlugin
    ) -> Any:
        return resolve_config_input(
            workload_cfg, plugin, self._logger, self._plugin_settings
        )
