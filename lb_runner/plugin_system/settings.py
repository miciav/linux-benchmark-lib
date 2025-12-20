"""Helpers for normalizing plugin settings and workload defaults."""

from __future__ import annotations

import logging
from dataclasses import asdict, is_dataclass
from inspect import isclass
from typing import Any, TYPE_CHECKING

from pydantic import BaseModel, ValidationError

if TYPE_CHECKING:
    from lb_runner.benchmark_config import BenchmarkConfig
    from lb_runner.plugin_system.registry import PluginRegistry


logger = logging.getLogger(__name__)


def _default_registry() -> "PluginRegistry":
    from lb_runner.plugin_system.builtin import builtin_plugins
    from lb_runner.plugin_system.registry import PluginRegistry

    return PluginRegistry(builtin_plugins())


def _resolve_registry(registry: "PluginRegistry | None") -> "PluginRegistry":
    return registry or _default_registry()


def hydrate_plugin_settings(
    config: "BenchmarkConfig",
    registry: "PluginRegistry | None" = None,
) -> None:
    """
    Convert plugin_settings dicts into their respective Pydantic models.

    This relies on the plugin registry to get the correct config_cls.
    """
    resolved = _resolve_registry(registry)

    for name, settings_data in list(config.plugin_settings.items()):
        try:
            plugin = resolved.get(name)
        except KeyError:
            logger.warning(
                "Plugin '%s' not found while hydrating plugin_settings; keeping raw value.",
                name,
            )
            continue
        config_cls = getattr(plugin, "config_cls", None)
        if not (config_cls and isclass(config_cls) and issubclass(config_cls, BaseModel)):
            logger.warning(
                "Plugin '%s' missing Pydantic config_cls; keeping settings as dict.",
                name,
            )
            continue
        if isinstance(settings_data, dict):
            try:
                config.plugin_settings[name] = config_cls.model_validate(settings_data)
            except ValidationError as exc:
                logger.error("Validation error for plugin '%s' config: %s", name, exc)


def populate_default_plugin_settings(
    config: "BenchmarkConfig",
    registry: "PluginRegistry | None" = None,
    load_entrypoints: bool = False,
    allow_dataclasses: bool = False,
) -> set[str]:
    """Populate default plugin settings for plugins that support it."""
    resolved = _resolve_registry(registry)
    available = resolved.available(load_entrypoints=load_entrypoints)
    created: set[str] = set()

    for name, plugin in available.items():
        if name in config.plugin_settings:
            continue
        config_cls = getattr(plugin, "config_cls", None)
        if config_cls and isclass(config_cls) and issubclass(config_cls, BaseModel):
            try:
                config.plugin_settings[name] = config_cls()
                created.add(name)
            except (ValidationError, TypeError) as exc:
                logger.debug("Skipping default config for plugin '%s': %s", name, exc)
            continue
        if allow_dataclasses and config_cls and isclass(config_cls) and is_dataclass(config_cls):
            try:
                config.plugin_settings[name] = config_cls()
                created.add(name)
            except TypeError as exc:
                logger.debug("Skipping default config for plugin '%s': %s", name, exc)

    return created


def ensure_workloads_from_plugin_settings(
    config: "BenchmarkConfig",
    dump_mode: str | None = None,
    convert_dataclasses: bool = False,
) -> None:
    """Populate workloads dict from plugin_settings if not explicitly defined."""
    if not config.plugin_settings:
        return

    from lb_runner.benchmark_config import WorkloadConfig

    def _settings_to_options(settings: Any) -> Any:
        if isinstance(settings, BaseModel):
            if dump_mode:
                return settings.model_dump(mode=dump_mode)
            return settings.model_dump()
        if convert_dataclasses and is_dataclass(settings):
            return asdict(settings)
        return settings

    for name, settings in config.plugin_settings.items():
        if name not in config.workloads:
            config.workloads[name] = WorkloadConfig(
                plugin=name,
                enabled=False,
                options=_settings_to_options(settings),
            )
        else:
            cfg = config.workloads[name]
            if not cfg.options:
                cfg.options = _settings_to_options(settings)


def apply_plugin_settings_defaults(
    config: "BenchmarkConfig",
    registry: "PluginRegistry | None" = None,
    load_entrypoints: bool = False,
) -> None:
    """Hydrate and backfill plugin-related settings on a BenchmarkConfig."""
    hydrate_plugin_settings(config, registry=registry)
    if not config.plugin_settings:
        populate_default_plugin_settings(
            config, registry=registry, load_entrypoints=load_entrypoints
        )
    ensure_workloads_from_plugin_settings(config)
