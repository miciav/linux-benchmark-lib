"""Public API helpers for workload plugins and registry."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, Protocol

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
from lb_plugins.installer import PluginInstaller
from lb_plugins.plugin_assets import PluginAssetConfig
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
from lb_plugins.plugins.baseline.plugin import (
    BaselineConfig,
    BaselineGenerator,
    BaselinePlugin,
    PLUGIN as BASELINE_PLUGIN,
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
from lb_plugins.plugins.dfaas.services.grafana_client import GrafanaClient

logger = logging.getLogger(__name__)

USER_PLUGIN_DIR = resolve_user_plugin_dir()
_REGISTRY_CACHE: PluginRegistry | None = None


class SupportsPluginAssets(Protocol):
    """Minimal interface for configs that store plugin asset metadata."""

    plugin_assets: Dict[str, PluginAssetConfig]


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


def plugin_metadata(registry: PluginRegistry) -> Dict[str, Dict[str, Any]]:
    """Return serializable metadata for available plugins (paths, descriptions, presets)."""
    data: Dict[str, Dict[str, Any]] = {}
    for name, plugin in registry.available(load_entrypoints=True).items():
        meta: Dict[str, Any] = {
            "name": name,
            "description": getattr(plugin, "description", ""),
            "ansible_setup_path": getattr(plugin, "get_ansible_setup_path", lambda: None)(),
            "ansible_teardown_path": getattr(plugin, "get_ansible_teardown_path", lambda: None)(),
            "ansible_setup_extravars": getattr(plugin, "get_ansible_setup_extravars", lambda: {})(),
            "ansible_teardown_extravars": getattr(plugin, "get_ansible_teardown_extravars", lambda: {})(),
        }
        data[name] = meta
    return data


def apply_plugin_assets(
    config: SupportsPluginAssets,
    registry: PluginRegistry,
) -> None:
    """Populate config.plugin_assets from resolved plugins."""
    assets: Dict[str, PluginAssetConfig] = {}
    for name, plugin in registry.available(load_entrypoints=True).items():
        setup_path = None
        teardown_path = None
        setup_extravars: Dict[str, Any] = {}
        teardown_extravars: Dict[str, Any] = {}
        if hasattr(plugin, "get_ansible_setup_path"):
            setup_path = plugin.get_ansible_setup_path()
        if hasattr(plugin, "get_ansible_teardown_path"):
            teardown_path = plugin.get_ansible_teardown_path()
        if hasattr(plugin, "get_ansible_setup_extravars"):
            setup_extravars = plugin.get_ansible_setup_extravars() or {}
        if hasattr(plugin, "get_ansible_teardown_extravars"):
            teardown_extravars = plugin.get_ansible_teardown_extravars() or {}
        assets[name] = PluginAssetConfig(
            setup_playbook=setup_path,
            teardown_playbook=teardown_path,
            setup_extravars=setup_extravars,
            teardown_extravars=teardown_extravars,
        )
    config.plugin_assets = assets


def collect_grafana_assets(
    registry: PluginRegistry,
    plugin_settings: Dict[str, Any] | None = None,
    enabled_plugins: Dict[str, bool] | None = None,
) -> GrafanaAssets:
    """Collect Grafana assets from enabled plugins, resolving datasource URLs."""
    settings = plugin_settings or {}
    datasources: list[GrafanaDatasourceAsset] = []
    dashboards: list[GrafanaDashboardAsset] = []
    for name, plugin in registry.available(load_entrypoints=True).items():
        if enabled_plugins is not None and not enabled_plugins.get(name, True):
            continue
        assets = plugin.get_grafana_assets()
        if not assets:
            continue
        config = settings.get(name)
        if config is None:
            try:
                config = plugin.config_cls()
            except Exception:
                config = None
        resolved = resolve_grafana_assets(assets, config)
        datasources.extend(resolved.datasources)
        dashboards.extend(resolved.dashboards)
    return GrafanaAssets(datasources=tuple(datasources), dashboards=tuple(dashboards))


__all__ = [
    "BaseGenerator",
    "CommandGenerator",
    "CommandSpec",
    "CommandSpecBuilder",
    "ResultParser",
    "BasePluginConfig",
    "WorkloadIntensity",
    "WorkloadPlugin",
    "SimpleWorkloadPlugin",
    "PluginRegistry",
    "PluginInstaller",
    "create_registry",
    "plugin_metadata",
    "build_plugin_table",
    "apply_plugin_assets",
    "apply_plugin_settings_defaults",
    "ensure_workloads_from_plugin_settings",
    "hydrate_plugin_settings",
    "populate_default_plugin_settings",
    "reset_registry_cache",
    "set_builtin_plugin_root",
    "get_builtin_plugin_root",
    "set_user_plugin_dir",
    "resolve_user_plugin_dir",
    "USER_PLUGIN_DIR",
    "builtin_plugins",
    "SupportsPluginAssets",
    "SupportsPluginSettings",
    "SupportsWorkloads",
    "WorkloadFactory",
    "PluginAssetConfig",
    "GrafanaAssets",
    "GrafanaDashboardAsset",
    "GrafanaDatasourceAsset",
    "resolve_grafana_assets",
    "collect_grafana_assets",
    "GrafanaClient",
    "BaselineConfig",
    "BaselineGenerator",
    "BaselinePlugin",
    "BASELINE_PLUGIN",
    "StressNGConfig",
    "StressNGGenerator",
    "StressNGPlugin",
    "SysbenchConfig",
    "SysbenchGenerator",
    "SysbenchPlugin",
    "DDConfig",
    "DDGenerator",
    "DDPlugin",
    "FIOConfig",
    "FIOGenerator",
    "FIOPlugin",
    "GeekbenchConfig",
    "GeekbenchGenerator",
    "GeekbenchPlugin",
    "HPLConfig",
    "HPLGenerator",
    "HPLPlugin",
    "StreamConfig",
    "StreamGenerator",
    "StreamPlugin",
    "UnixBenchConfig",
    "UnixBenchGenerator",
    "UnixBenchPlugin",
    "YabsConfig",
    "YabsGenerator",
    "YabsPlugin",
    "PhoronixConfig",
    "PhoronixGenerator",
    "PhoronixTestSuiteWorkloadPlugin",
    "get_phoronix_plugins",
    "DEFAULT_NTIMES",
    "DEFAULT_STREAM_ARRAY_SIZE",
]
