"""Helpers for building RunContext instances."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, List, Optional

from lb_controller.api import (
    BenchmarkConfig,
    PlatformConfig,
    apply_playbook_defaults,
)
from lb_plugins.api import PluginRegistry, apply_plugin_assets, create_registry

from lb_app.services.config_defaults import apply_platform_defaults
from lb_app.services.run_types import RunContext
from lb_app.ui_interfaces import UIAdapter


def apply_overrides(
    cfg: BenchmarkConfig, intensity: str | None, debug: bool
) -> None:
    """Apply CLI-driven overrides to the configuration."""
    if intensity:
        for wl_name in cfg.workloads:
            cfg.workloads[wl_name].intensity = intensity
    if debug:
        for workload in cfg.workloads.values():
            if isinstance(workload.options, dict):
                workload.options["debug"] = True
            else:
                try:
                    setattr(workload.options, "debug", True)
                except Exception:
                    pass


def resolve_target_tests(
    cfg: BenchmarkConfig,
    tests: Optional[List[str]],
    platform_config: PlatformConfig,
    ui_adapter: UIAdapter | None,
) -> List[str]:
    """Determine which workloads to run, skipping those disabled by platform."""
    target_tests = tests or list(cfg.workloads.keys())
    if not target_tests:
        raise ValueError("No workloads selected to run.")

    disabled: list[str] = []
    allowed: list[str] = []
    for name in target_tests:
        workload = cfg.workloads.get(name)
        plugin_name = workload.plugin if workload else name
        if not platform_config.is_plugin_enabled(plugin_name):
            disabled.append(name)
            continue
        allowed.append(name)

    if disabled and ui_adapter:
        ui_adapter.show_warning(
            "Skipping workloads disabled by platform config: "
            + ", ".join(sorted(disabled))
        )
    if not allowed:
        raise ValueError("All selected workloads are disabled by platform config.")
    return allowed


class RunContextBuilder:
    """Build RunContext instances from user inputs and config services."""

    def __init__(self, registry_factory: Callable[[], PluginRegistry]) -> None:
        self._registry_factory = registry_factory

    def build_context(
        self,
        cfg: BenchmarkConfig,
        tests: Optional[List[str]],
        config_path: Optional[Path] = None,
        debug: bool = False,
        resume: Optional[str] = None,
        stop_file: Optional[Path] = None,
        execution_mode: str = "remote",
        node_count: int | None = None,
    ) -> RunContext:
        """Compute the run context and registry."""
        registry = self._registry_factory()
        target_tests = tests or list(cfg.workloads.keys())
        return RunContext(
            config=cfg,
            target_tests=target_tests,
            registry=registry,
            config_path=config_path,
            debug=debug,
            resume_from=None if resume in (None, "latest") else resume,
            resume_latest=resume == "latest",
            stop_file=stop_file,
            execution_mode=execution_mode,
            node_count=node_count,
        )

    def create_session(
        self,
        config_service: Any,
        tests: Optional[List[str]] = None,
        config_path: Optional[Path] = None,
        run_id: Optional[str] = None,
        resume: Optional[str] = None,
        repetitions: Optional[int] = None,
        debug: bool = False,
        intensity: Optional[str] = None,
        ui_adapter: UIAdapter | None = None,
        setup: bool = True,
        stop_file: Optional[Path] = None,
        execution_mode: str = "remote",
        node_count: int | None = None,
        preloaded_config: BenchmarkConfig | None = None,
    ) -> RunContext:
        """
        Orchestrate the creation of a RunContext from raw inputs.

        This method consolidates configuration loading, overrides, and context building.
        """
        cfg, resolved = self._load_or_default_config(
            config_service, config_path, ui_adapter, preloaded_config
        )
        platform_config, _, _ = config_service.load_platform_config()
        apply_platform_defaults(cfg, platform_config)
        apply_playbook_defaults(cfg)
        self._apply_setup_overrides(
            cfg, setup, repetitions, intensity, ui_adapter, debug
        )
        target_tests = resolve_target_tests(
            cfg, tests, platform_config, ui_adapter
        )
        context = self.build_context(
            cfg,
            target_tests,
            config_path=resolved,
            debug=debug,
            resume=resume,
            stop_file=stop_file,
            execution_mode=execution_mode,
            node_count=node_count,
        )
        _ = run_id
        return context

    def _load_or_default_config(
        self,
        config_service: Any,
        config_path: Optional[Path],
        ui_adapter: UIAdapter | None,
        preloaded_config: BenchmarkConfig | None,
    ) -> tuple[BenchmarkConfig, Optional[Path]]:
        """Load config from disk or return a provided instance with UI feedback."""
        if preloaded_config is not None:
            if not preloaded_config.plugin_assets:
                apply_plugin_assets(preloaded_config, create_registry())
            return preloaded_config, config_path
        cfg, resolved, stale = config_service.load_for_read(config_path)
        if not cfg.plugin_assets:
            apply_plugin_assets(cfg, create_registry())
        if ui_adapter:
            if stale:
                ui_adapter.show_warning(f"Saved default config not found: {stale}")
            if resolved:
                ui_adapter.show_success(f"Loaded config: {resolved}")
            else:
                ui_adapter.show_warning(
                    "No config file found; using built-in defaults."
                )
        return cfg, resolved

    def _apply_setup_overrides(
        self,
        cfg: BenchmarkConfig,
        setup: bool,
        repetitions: Optional[int],
        intensity: Optional[str],
        ui_adapter: UIAdapter | None,
        debug: bool,
    ) -> None:
        """Apply CLI flags to config and ensure directories exist."""
        cfg.remote_execution.run_setup = setup
        if not setup:
            cfg.remote_execution.run_teardown = False
        cfg.remote_execution.enabled = True
        if repetitions is not None:
            cfg.repetitions = repetitions
            if ui_adapter:
                ui_adapter.show_info(f"Using {repetitions} repetitions for this run")
        apply_overrides(cfg, intensity=intensity, debug=debug)
        if intensity and ui_adapter:
            ui_adapter.show_info(f"Global intensity override: {intensity}")
        cfg.ensure_output_dirs()
