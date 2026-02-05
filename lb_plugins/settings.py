"""Helpers for normalizing plugin settings and workload defaults."""

from __future__ import annotations

import logging
from dataclasses import asdict, is_dataclass
from inspect import isclass
from typing import Any, Dict, Protocol

from pydantic import BaseModel, ValidationError

from lb_plugins.builtin import builtin_plugins
from lb_plugins.registry import PluginRegistry

logger = logging.getLogger(__name__)


class SupportsPluginSettings(Protocol):
    """Minimal interface for configs that store plugin settings."""

    plugin_settings: Dict[str, Any]


class SupportsWorkloads(Protocol):
    """Minimal interface for configs that store workloads."""

    workloads: Dict[str, Any]


class WorkloadFactory(Protocol):
    """Factory for workload config objects."""

    def __call__(self, *, plugin: str, options: Dict[str, Any]) -> Any:
        ...


def _default_registry() -> PluginRegistry:
    return PluginRegistry(builtin_plugins())


def _resolve_registry(registry: PluginRegistry | None) -> PluginRegistry:
    return registry or _default_registry()


def hydrate_plugin_settings(
    config: SupportsPluginSettings,
    registry: PluginRegistry | None = None,
) -> None:
    """
    Convert plugin_settings dicts into their respective Pydantic models.

    This relies on the plugin registry to get the correct config_cls.
    """
    resolved = _resolve_registry(registry)

    for name, settings_data in list(config.plugin_settings.items()):
        _hydrate_plugin_setting(config, resolved, name, settings_data)


def populate_default_plugin_settings(
    config: SupportsPluginSettings,
    registry: PluginRegistry | None = None,
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
        if _try_create_default_setting(config, name, plugin, allow_dataclasses):
            created.add(name)

    return created


def ensure_workloads_from_plugin_settings(
    config: SupportsPluginSettings & SupportsWorkloads,
    workload_factory: WorkloadFactory,
    dump_mode: str | None = None,
    convert_dataclasses: bool = False,
) -> None:
    """Populate workloads dict from plugin_settings if not explicitly defined."""
    if not config.plugin_settings:
        return

    for name, settings in config.plugin_settings.items():
        _ensure_workload(
            config,
            workload_factory=workload_factory,
            name=name,
            settings=settings,
            dump_mode=dump_mode,
            convert_dataclasses=convert_dataclasses,
        )


def apply_plugin_settings_defaults(
    config: SupportsPluginSettings & SupportsWorkloads,
    registry: PluginRegistry | None = None,
    load_entrypoints: bool = False,
    workload_factory: WorkloadFactory | None = None,
    dump_mode: str | None = None,
    convert_dataclasses: bool = False,
) -> None:
    """Hydrate and backfill plugin-related settings on a config object."""
    hydrate_plugin_settings(config, registry=registry)
    if not config.plugin_settings:
        populate_default_plugin_settings(
            config, registry=registry, load_entrypoints=load_entrypoints
        )
    if workload_factory is None:
        raise ValueError("workload_factory is required to backfill workloads")
    ensure_workloads_from_plugin_settings(
        config,
        workload_factory=workload_factory,
        dump_mode=dump_mode,
        convert_dataclasses=convert_dataclasses,
    )


def _hydrate_plugin_setting(
    config: SupportsPluginSettings,
    registry: PluginRegistry,
    name: str,
    settings_data: Any,
) -> None:
    try:
        plugin = registry.get(name)
    except KeyError:
        logger.warning(
            "Plugin '%s' not found while hydrating plugin_settings; keeping raw value.",
            name,
        )
        return

    config_cls = getattr(plugin, "config_cls", None)
    if not _is_pydantic_config(config_cls):
        logger.warning(
            "Plugin '%s' missing Pydantic config_cls; keeping settings as dict.",
            name,
        )
        return

    if isinstance(settings_data, dict):
        try:
            config.plugin_settings[name] = config_cls.model_validate(settings_data)
        except ValidationError as exc:
            logger.error("Validation error for plugin '%s' config: %s", name, exc)


def _is_pydantic_config(config_cls: Any) -> bool:
    return bool(
        config_cls and isclass(config_cls) and issubclass(config_cls, BaseModel)
    )


def _is_dataclass_config(config_cls: Any) -> bool:
    return bool(config_cls and isclass(config_cls) and is_dataclass(config_cls))


def _try_create_default_setting(
    config: SupportsPluginSettings,
    name: str,
    plugin: Any,
    allow_dataclasses: bool,
) -> bool:
    config_cls = getattr(plugin, "config_cls", None)
    if _is_pydantic_config(config_cls):
        return _instantiate_setting(config, name, config_cls)
    if allow_dataclasses and _is_dataclass_config(config_cls):
        return _instantiate_setting(config, name, config_cls)
    return False


def _instantiate_setting(
    config: SupportsPluginSettings, name: str, config_cls: Any
) -> bool:
    try:
        config.plugin_settings[name] = config_cls()
        return True
    except (ValidationError, TypeError) as exc:
        logger.debug("Skipping default config for plugin '%s': %s", name, exc)
        return False


def _ensure_workload(
    config: SupportsPluginSettings & SupportsWorkloads,
    workload_factory: WorkloadFactory,
    name: str,
    settings: Any,
    dump_mode: str | None,
    convert_dataclasses: bool,
) -> None:
    options = _settings_to_options(settings, dump_mode, convert_dataclasses)
    if name not in config.workloads:
        config.workloads[name] = workload_factory(plugin=name, options=options)
        return
    cfg = config.workloads[name]
    if not getattr(cfg, "options", None):
        cfg.options = options


def _settings_to_options(
    settings: Any, dump_mode: str | None, convert_dataclasses: bool
) -> Any:
    if isinstance(settings, BaseModel):
        if dump_mode:
            return settings.model_dump(mode=dump_mode)
        return settings.model_dump()
    if convert_dataclasses and is_dataclass(settings):
        return asdict(settings)
    return settings
