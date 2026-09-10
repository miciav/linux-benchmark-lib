"""Public API helpers for workload plugins and registry."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Protocol

from lb_common.api import GrafanaClient
from lb_plugins import discovery as discovery_module
from lb_plugins import registry as registry_module
from lb_plugins.base_generator import (
    BaseGenerator,
    CommandGenerator,
    CommandSpec,
    CommandSpecBuilder,
    ResultParser,
)
from lb_plugins.builtin import builtin_plugins
from lb_plugins.discovery import resolve_user_plugin_dir
from lb_plugins.installer import PluginInstaller
from lb_plugins.interface import (
    BasePluginConfig,
    SimpleWorkloadPlugin,
    WorkloadIntensity,
    WorkloadPlugin,
)
from lb_plugins.observability import (
    GrafanaAssets,
    GrafanaDashboardAsset,
    GrafanaDatasourceAsset,
    resolve_grafana_assets,
)
from lb_plugins.plugin_assets import PluginAssetConfig
from lb_plugins.plugins.baseline.plugin import (
    PLUGIN as BASELINE_PLUGIN,
)
from lb_plugins.plugins.baseline.plugin import (
    BaselineConfig,
    BaselineGenerator,
    BaselinePlugin,
)
from lb_plugins.plugins.dd.plugin import DDConfig, DDGenerator, DDPlugin
from lb_plugins.plugins.fio.plugin import FIOConfig, FIOGenerator, FIOPlugin
from lb_plugins.plugins.geekbench.plugin import (
    GeekbenchConfig,
    GeekbenchGenerator,
    GeekbenchPlugin,
)
from lb_plugins.plugins.hpl.plugin import HPLConfig, HPLGenerator, HPLPlugin
from lb_plugins.plugins.phoronix_test_suite.plugin import (
    PhoronixConfig,
    PhoronixGenerator,
    PhoronixTestSuiteWorkloadPlugin,
)
from lb_plugins.plugins.phoronix_test_suite.plugin import (
    get_plugins as get_phoronix_plugins,
)
from lb_plugins.plugins.stream.plugin import (
    DEFAULT_NTIMES,
    DEFAULT_STREAM_ARRAY_SIZE,
    StreamConfig,
    StreamGenerator,
    StreamPlugin,
)
from lb_plugins.plugins.stress_ng.plugin import (
    StressNGConfig,
    StressNGGenerator,
    StressNGPlugin,
)
from lb_plugins.plugins.sysbench.plugin import (
    SysbenchConfig,
    SysbenchGenerator,
    SysbenchPlugin,
)
from lb_plugins.plugins.unixbench.plugin import (
    UnixBenchConfig,
    UnixBenchGenerator,
    UnixBenchPlugin,
)
from lb_plugins.plugins.yabs.plugin import YabsConfig, YabsGenerator, YabsPlugin
from lb_plugins.registry import PluginRegistry
from lb_plugins.settings import (
    SupportsPluginSettings,
    SupportsWorkloads,
    WorkloadFactory,
    apply_plugin_settings_defaults,
    ensure_workloads_from_plugin_settings,
    hydrate_plugin_settings,
    populate_default_plugin_settings,
)
from lb_plugins.table import build_plugin_table

logger = logging.getLogger(__name__)

USER_PLUGIN_DIR = resolve_user_plugin_dir()
_REGISTRY_CACHE: PluginRegistry | None = None


class SupportsPluginAssets(Protocol):
    """Minimal interface for configs that store plugin asset metadata."""

    plugin_assets: dict[str, PluginAssetConfig]


def create_registry(refresh: bool = False) -> PluginRegistry:
    """Build a plugin registry with built-ins, entry points, and user plugins."""
    global _REGISTRY_CACHE
    if not refresh and _REGISTRY_CACHE is not None:
        return _REGISTRY_CACHE
    _REGISTRY_CACHE = PluginRegistry(builtin_plugins())
    return _REGISTRY_CACHE


def reset_registry_cache() -> None:
    """Clear the cached registry so changes are picked up."""
    global _REGISTRY_CACHE
    _REGISTRY_CACHE = None


def set_user_plugin_dir(path: Path) -> Path:
    """Override the user plugin directory via environment."""
    os.environ["LB_USER_PLUGIN_DIR"] = str(path)
    resolved = resolve_user_plugin_dir()
    global USER_PLUGIN_DIR
    USER_PLUGIN_DIR = resolved
    discovery_module.USER_PLUGIN_DIR = resolved
    registry_module.USER_PLUGIN_DIR = resolved
    reset_registry_cache()
    return resolved


def set_builtin_plugin_root(path: Path) -> Path:
    """Override the builtin plugin root for resolving user plugins."""
    resolved = path.expanduser().resolve()
    discovery_module.BUILTIN_PLUGIN_ROOT = resolved
    registry_module.BUILTIN_PLUGIN_ROOT = resolved
    resolved = resolve_user_plugin_dir()
    global USER_PLUGIN_DIR
    USER_PLUGIN_DIR = resolved
    discovery_module.USER_PLUGIN_DIR = resolved
    registry_module.USER_PLUGIN_DIR = resolved
    reset_registry_cache()
    return resolved


def get_builtin_plugin_root() -> Path:
    """Return the current builtin plugin root path."""
    return discovery_module.BUILTIN_PLUGIN_ROOT


def plugin_metadata(registry: PluginRegistry) -> dict[str, dict[str, Any]]:
    """Return serializable metadata for available plugins."""
    data: dict[str, dict[str, Any]] = {}
    for name, plugin in registry.available(load_entrypoints=True).items():
        data[name] = _build_plugin_metadata(name, plugin)
    return data


def apply_plugin_assets(
    config: SupportsPluginAssets,
    registry: PluginRegistry,
) -> None:
    """Populate config.plugin_assets from resolved plugins."""
    assets: dict[str, PluginAssetConfig] = {}
    for name, plugin in registry.available(load_entrypoints=True).items():
        assets[name] = _build_plugin_assets(plugin)
    config.plugin_assets = assets


def merge_plugin_assets(
    config: SupportsPluginAssets,
    registry: PluginRegistry,
) -> None:
    """Merge user-provided plugin assets with registry defaults.

    User overrides are preserved, while required UV extras fall back to plugin
    defaults when omitted so runtime dependencies stay installable.
    """
    existing_assets = dict(config.plugin_assets or {})
    apply_plugin_assets(config, registry)
    if not existing_assets:
        return

    merged_assets = dict(config.plugin_assets)
    for name, user_asset in existing_assets.items():
        default_asset = merged_assets.get(name)
        if default_asset is None:
            merged_assets[name] = user_asset
            continue

        merged = user_asset.model_copy(deep=True)
        if not merged.required_uv_extras and default_asset.required_uv_extras:
            merged.required_uv_extras = list(default_asset.required_uv_extras)
        merged_assets[name] = merged

    config.plugin_assets = merged_assets


def collect_grafana_assets(
    registry: PluginRegistry,
    plugin_settings: dict[str, Any] | None = None,
    enabled_plugins: dict[str, bool] | None = None,
    remote_hosts: list[Any] | None = None,
) -> GrafanaAssets:
    """Collect Grafana assets from enabled plugins, resolving datasource URLs."""
    settings = plugin_settings or {}
    datasources: list[GrafanaDatasourceAsset] = []
    dashboards: list[GrafanaDashboardAsset] = []
    for name, plugin in registry.available(load_entrypoints=True).items():
        if enabled_plugins is not None and not enabled_plugins.get(name, True):
            continue
        resolved = _resolve_grafana_assets_for_plugin(
            plugin,
            settings,
            name=name,
            hosts=remote_hosts,
        )
        if resolved is None:
            continue
        datasources.extend(resolved.datasources)
        dashboards.extend(resolved.dashboards)
    return GrafanaAssets(datasources=tuple(datasources), dashboards=tuple(dashboards))


def _build_plugin_metadata(name: str, plugin: Any) -> dict[str, Any]:
    return {
        "name": name,
        "description": getattr(plugin, "description", ""),
        "ansible_setup_path": _call_plugin_method(plugin, "get_ansible_setup_path"),
        "ansible_teardown_path": _call_plugin_method(
            plugin, "get_ansible_teardown_path"
        ),
        "ansible_setup_extravars": _call_plugin_method(
            plugin, "get_ansible_setup_extravars", default={}
        ),
        "ansible_teardown_extravars": _call_plugin_method(
            plugin, "get_ansible_teardown_extravars", default={}
        ),
    }


def _call_plugin_method(plugin: Any, name: str, default: Any = None) -> Any:
    method = getattr(plugin, name, None)
    if method is None:
        return default
    return method()


def _build_plugin_assets(plugin: Any) -> PluginAssetConfig:
    return PluginAssetConfig(
        setup_playbook=_call_plugin_method(plugin, "get_ansible_setup_path"),
        teardown_playbook=_call_plugin_method(plugin, "get_ansible_teardown_path"),
        setup_extravars=_call_plugin_method(
            plugin, "get_ansible_setup_extravars", default={}
        )
        or {},
        teardown_extravars=_call_plugin_method(
            plugin, "get_ansible_teardown_extravars", default={}
        )
        or {},
        collect_pre_playbook=_call_plugin_method(
            plugin, "get_ansible_collect_pre_path"
        ),
        collect_post_playbook=_call_plugin_method(
            plugin, "get_ansible_collect_post_path"
        ),
        collect_pre_extravars=_call_plugin_method(
            plugin, "get_ansible_collect_pre_extravars", default={}
        )
        or {},
        collect_post_extravars=_call_plugin_method(
            plugin, "get_ansible_collect_post_extravars", default={}
        )
        or {},
        required_uv_extras=_call_plugin_method(
            plugin, "get_required_uv_extras", default=[]
        )
        or [],
    )


def _resolve_grafana_assets_for_plugin(
    plugin: Any,
    settings: dict[str, Any],
    *,
    name: str,
    hosts: list[Any] | None,
) -> GrafanaAssets | None:
    assets = plugin.get_grafana_assets()
    if not assets:
        return None
    config = settings.get(name)
    if config is None:
        config = _default_plugin_config(plugin)
    return resolve_grafana_assets(assets, config, hosts=hosts)


def _default_plugin_config(plugin: Any) -> Any | None:
    try:
        return plugin.config_cls()
    except Exception:
        return None


__all__ = [
    "BASELINE_PLUGIN",
    "DEFAULT_NTIMES",
    "DEFAULT_STREAM_ARRAY_SIZE",
    "USER_PLUGIN_DIR",
    "BaseGenerator",
    "BasePluginConfig",
    "BaselineConfig",
    "BaselineGenerator",
    "BaselinePlugin",
    "CommandGenerator",
    "CommandSpec",
    "CommandSpecBuilder",
    "DDConfig",
    "DDGenerator",
    "DDPlugin",
    "FIOConfig",
    "FIOGenerator",
    "FIOPlugin",
    "GeekbenchConfig",
    "GeekbenchGenerator",
    "GeekbenchPlugin",
    "GrafanaAssets",
    "GrafanaClient",
    "GrafanaDashboardAsset",
    "GrafanaDatasourceAsset",
    "HPLConfig",
    "HPLGenerator",
    "HPLPlugin",
    "PhoronixConfig",
    "PhoronixGenerator",
    "PhoronixTestSuiteWorkloadPlugin",
    "PluginAssetConfig",
    "PluginInstaller",
    "PluginRegistry",
    "ResultParser",
    "SimpleWorkloadPlugin",
    "StreamConfig",
    "StreamGenerator",
    "StreamPlugin",
    "StressNGConfig",
    "StressNGGenerator",
    "StressNGPlugin",
    "SupportsPluginAssets",
    "SupportsPluginSettings",
    "SupportsWorkloads",
    "SysbenchConfig",
    "SysbenchGenerator",
    "SysbenchPlugin",
    "UnixBenchConfig",
    "UnixBenchGenerator",
    "UnixBenchPlugin",
    "WorkloadFactory",
    "WorkloadIntensity",
    "WorkloadPlugin",
    "YabsConfig",
    "YabsGenerator",
    "YabsPlugin",
    "apply_plugin_assets",
    "apply_plugin_settings_defaults",
    "build_plugin_table",
    "builtin_plugins",
    "collect_grafana_assets",
    "create_registry",
    "ensure_workloads_from_plugin_settings",
    "get_builtin_plugin_root",
    "get_phoronix_plugins",
    "hydrate_plugin_settings",
    "merge_plugin_assets",
    "plugin_metadata",
    "populate_default_plugin_settings",
    "reset_registry_cache",
    "resolve_grafana_assets",
    "resolve_user_plugin_dir",
    "set_builtin_plugin_root",
    "set_user_plugin_dir",
]
