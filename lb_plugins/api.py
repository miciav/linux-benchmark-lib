"""Public API helpers for workload plugins and registry."""

from __future__ import annotations

import logging
import os
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional, Protocol, Union

from lb_plugins import registry as registry_module
from lb_plugins.base_generator import BaseGenerator
from lb_plugins.builtin import builtin_plugins
from lb_plugins.interface import BasePluginConfig, WorkloadIntensity, WorkloadPlugin
from lb_plugins.plugin_assets import PluginAssetConfig
from lb_plugins.registry import PluginRegistry, resolve_user_plugin_dir
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
from lb_plugins.plugins.dd.plugin import DDConfig, DDPlugin
from lb_plugins.plugins.fio.plugin import FIOConfig, FIOGenerator, FIOPlugin
from lb_plugins.plugins.geekbench.plugin import (
    GeekbenchConfig,
    GeekbenchGenerator,
    GeekbenchPlugin,
)
from lb_plugins.plugins.hpl.plugin import HPLConfig, HPLPlugin
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
from lb_plugins.plugins.stress_ng.plugin import StressNGConfig
from lb_plugins.plugins.yabs.plugin import YabsConfig, YabsGenerator, YabsPlugin

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
    reset_registry_cache()
    return resolved


def set_builtin_plugin_root(path: Path) -> Path:
    """Override the builtin plugin root for resolving user plugins."""
    registry_module.BUILTIN_PLUGIN_ROOT = path.expanduser().resolve()
    resolved = resolve_user_plugin_dir()
    global USER_PLUGIN_DIR
    USER_PLUGIN_DIR = resolved
    reset_registry_cache()
    return resolved


def get_builtin_plugin_root() -> Path:
    """Return the current builtin plugin root path."""
    return registry_module.BUILTIN_PLUGIN_ROOT


class PluginInstaller:
    """Helper to install and uninstall user plugins."""

    def __init__(self) -> None:
        self.plugin_dir = resolve_user_plugin_dir()
        self.plugin_dir.mkdir(parents=True, exist_ok=True)

    def install(self, source_path: Union[Path, str], manifest_path: Optional[Path] = None, force: bool = False) -> str:
        """Install a plugin from file/dir/archive/git URL."""
        raw_source = str(source_path)
        if self._looks_like_git_url(raw_source):
            return self._install_from_git(raw_source, force)

        path = Path(raw_source).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Source not found: {path}")

        if path.is_dir():
            return self._install_directory(path, force)
        if path.suffix == ".py":
            return self._install_file(path, manifest_path, force)
        if self._is_supported_archive(path):
            return self._install_archive(path, force)
        raise ValueError(f"Unsupported source: {path}")

    def package(self, source_dir: Path, archive_path: Path) -> Path:
        """Package a plugin directory into a supported archive format."""
        source_dir = source_dir.resolve()
        if not source_dir.is_dir():
            raise ValueError(f"Source directory not found: {source_dir}")
        archive_path = archive_path.resolve()
        archive_path.parent.mkdir(parents=True, exist_ok=True)

        if archive_path.suffix == ".zip":
            with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zip_ref:
                for path in source_dir.rglob("*"):
                    zip_ref.write(path, path.relative_to(source_dir.parent))
            return archive_path

        name = archive_path.name
        mode = None
        if name.endswith(".tar.gz") or name.endswith(".tgz"):
            mode = "w:gz"
        elif name.endswith(".tar.bz2"):
            mode = "w:bz2"
        elif name.endswith(".tar.xz"):
            mode = "w:xz"
        elif name.endswith(".tar"):
            mode = "w"
        elif archive_path.suffix in {".gz", ".bz2", ".xz"}:
            mode = "w:*"
        if mode is None:
            raise ValueError(f"Unsupported archive format: {archive_path}")

        with tarfile.open(archive_path, mode) as tar_ref:
            tar_ref.add(source_dir, arcname=source_dir.name)
        return archive_path

    def uninstall(self, plugin_name: str) -> bool:
        """Remove plugin artifacts from the user plugin dir."""
        target_py = self.plugin_dir / f"{plugin_name}.py"
        target_yaml = self.plugin_dir / f"{plugin_name}.yaml"
        target_yml = self.plugin_dir / f"{plugin_name}.yml"
        target_dir = self.plugin_dir / plugin_name
        found = False
        if target_dir.exists() and target_dir.is_dir():
            shutil.rmtree(target_dir)
            found = True
        if target_py.exists():
            target_py.unlink()
            found = True
        for manifest in (target_yaml, target_yml):
            if manifest.exists():
                manifest.unlink()
        if not found:
            logger.warning("Plugin '%s' not found in user directory.", plugin_name)
        return found

    def _install_file(self, py_path: Path, manifest_path: Optional[Path], force: bool) -> str:
        target_py = self.plugin_dir / py_path.name
        if target_py.exists() and not force:
            raise FileExistsError(f"Plugin '{py_path.stem}' already exists. Use --force to overwrite.")
        shutil.copy2(py_path, target_py)
        if manifest_path:
            target_manifest = self.plugin_dir / f"{py_path.stem}.yaml"
            shutil.copy2(manifest_path, target_manifest)
        return py_path.stem

    def _install_archive(self, archive_path: Path, force: bool) -> str:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            if archive_path.suffix == ".zip":
                with zipfile.ZipFile(archive_path, "r") as zip_ref:
                    zip_ref.extractall(tmp_path)
            else:
                with tarfile.open(archive_path, "r") as tar_ref:
                    tar_ref.extractall(tmp_path, filter="data")
            items = list(tmp_path.iterdir())
            source_dir = items[0] if len(items) == 1 and items[0].is_dir() else tmp_path
            return self._install_directory(source_dir, force)

    def _install_directory(self, source_dir: Path, force: bool) -> str:
        source_dir = source_dir.resolve()
        py_files = list(source_dir.glob("*.py"))
        if not py_files and not any(source_dir.rglob("*.py")):
            raise ValueError(f"Directory '{source_dir.name}' does not contain any Python files.")

        if len(py_files) == 1 and (source_dir / "__init__.py").exists():
            module = py_files[0]
            plugin_name = module.stem
            target_py = self.plugin_dir / f"{plugin_name}.py"
            if target_py.exists() and not force:
                raise FileExistsError(f"Plugin '{plugin_name}' already exists at {target_py}. Use --force to overwrite.")
            if target_py.exists():
                target_py.unlink()
            shutil.copy2(module, target_py)
            return plugin_name

        plugin_name = source_dir.name
        target_dir = self.plugin_dir / plugin_name
        if target_dir.exists():
            if not force:
                raise FileExistsError(f"Plugin '{plugin_name}' already exists at {target_dir}. Use --force to overwrite.")
            if target_dir.is_dir():
                shutil.rmtree(target_dir)
            else:
                target_dir.unlink()
        shutil.copytree(source_dir, target_dir)
        return plugin_name

    @staticmethod
    def _looks_like_git_url(raw: str) -> bool:
        return raw.startswith(("git@", "http://", "https://", "file://"))

    @staticmethod
    def _is_supported_archive(path: Path) -> bool:
        return path.suffix in {".zip", ".gz", ".tgz", ".bz2", ".xz"}

    def _install_from_git(self, url: str, force: bool) -> str:
        import subprocess

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_name = self._infer_repo_name(url)
            tmp_path = Path(tmp_dir) / repo_name
            cmd = ["git", "clone", url, str(tmp_path)]
            if force:
                cmd.insert(2, "--depth=1")
            subprocess.run(cmd, check=True, capture_output=True)
            return self._install_directory(tmp_path, force)

    @staticmethod
    def _infer_repo_name(url: str) -> str:
        raw = url.rstrip("/")
        if raw.endswith(".git"):
            raw = raw[: -len(".git")]
        if "://" in raw:
            raw = raw.split("://", 1)[1]
        if ":" in raw and "/" not in raw.split(":", 1)[0]:
            raw = raw.split(":", 1)[1]
        name = raw.rsplit("/", 1)[-1]
        return name or "plugin"


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


__all__ = [
    "BaseGenerator",
    "BasePluginConfig",
    "WorkloadIntensity",
    "WorkloadPlugin",
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
    "BaselineConfig",
    "BaselineGenerator",
    "BaselinePlugin",
    "BASELINE_PLUGIN",
    "StressNGConfig",
    "DDConfig",
    "DDPlugin",
    "FIOConfig",
    "FIOGenerator",
    "FIOPlugin",
    "GeekbenchConfig",
    "GeekbenchGenerator",
    "GeekbenchPlugin",
    "HPLConfig",
    "HPLPlugin",
    "StreamConfig",
    "StreamGenerator",
    "StreamPlugin",
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
