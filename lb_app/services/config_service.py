"""Configuration resolution and mutation helpers for the CLI."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from lb_controller.api import (
    BenchmarkConfig,
    PlatformConfig,
    RemoteHostConfig,
    WorkloadConfig,
    apply_playbook_defaults,
)
from lb_plugins.api import (
    apply_plugin_assets,
    create_registry,
    PluginRegistry,
    hydrate_plugin_settings,
)
from lb_app.services.config_defaults import apply_platform_defaults
from lb_app.services.config_repository import ConfigRepository


class ConfigService:
    """Resolve, load, and mutate BenchmarkConfig files."""

    def __init__(self, config_home: Optional[Path] = None) -> None:
        self._repo = ConfigRepository(config_home)

    def ensure_home(self) -> None:
        """Create the config home directory."""
        self._repo.ensure_home()

    def open_editor(self, config_path: Optional[Path]) -> Path:
        """
        Open the resolved config file in the system editor.
        """
        resolved, stale = self.resolve_config_path(config_path)
        if resolved is None:
            raise FileNotFoundError("No config file found to edit. Run `lb config init` first.")

        editor = os.environ.get("EDITOR")
        if not editor:
            raise EnvironmentError(f"Set $EDITOR or open the file manually: {resolved}")

        try:
            subprocess.run([editor, str(resolved)], check=False)
        except Exception as exc:
            raise RuntimeError(f"Failed to launch editor: {exc}") from exc

        return resolved

    def resolve_config_path(self, config_path: Optional[Path]) -> Tuple[Optional[Path], Optional[Path]]:
        """
        Return (resolved_config, stale_pointer_target).
        Respects explicit path, environment variable LB_CONFIG_PATH, stored pointer, or local benchmark_config.json.
        """
        return self._repo.resolve_config_path(config_path)

    def _hydrate_config(self, cfg: BenchmarkConfig) -> None:
        """
        Convert raw dictionary configs in plugin_settings to Typed Config Objects.
        This requires looking up the plugin definition in the registry.
        """
        registry = create_registry()
        hydrate_plugin_settings(cfg, registry=registry)
        apply_plugin_assets(cfg, registry)
        apply_playbook_defaults(cfg)

    def create_default_config(self) -> BenchmarkConfig:
        """Create a fresh BenchmarkConfig with no workloads selected."""
        cfg = BenchmarkConfig()
        cfg.workloads = {}
        cfg.plugin_settings = {}
        apply_plugin_assets(cfg, create_registry())
        apply_playbook_defaults(cfg)
        return cfg

    @staticmethod
    def apply_platform_defaults(
        cfg: BenchmarkConfig, platform_config: PlatformConfig
    ) -> None:
        """Apply platform defaults without mutating workload selection."""
        apply_platform_defaults(cfg, platform_config)

    def load_platform_config(self) -> tuple[PlatformConfig, Path, bool]:
        """Load platform config from ~/.config/lb/platform.json (empty if missing)."""
        cfg = self._repo.read_platform_config()
        if cfg is not None:
            return cfg, self._repo.platform_target, True
        return PlatformConfig(), self._repo.platform_target, False

    def load_platform_for_write(self) -> tuple[PlatformConfig, Path]:
        """Load platform config (create default if missing) for mutation."""
        cfg, target, _ = self.load_platform_config()
        return cfg, target

    def set_plugin_enabled(
        self,
        name: str,
        enabled: bool,
    ) -> tuple[PlatformConfig, Path]:
        """Enable/disable a plugin in platform config."""
        cfg, target = self.load_platform_for_write()
        cfg.plugins[name] = enabled
        self._repo.write_platform_config(cfg, target)
        return cfg, target

    def set_plugin_selection(
        self,
        selection: set[str],
        registry: PluginRegistry,
    ) -> tuple[PlatformConfig, Path]:
        """Persist plugin selection to platform config."""
        cfg, target = self.load_platform_for_write()
        cfg.plugins = {name: name in selection for name in registry.available()}
        self._repo.write_platform_config(cfg, target)
        return cfg, target

    def load_for_read(self, config_path: Optional[Path]) -> Tuple[BenchmarkConfig, Optional[Path], Optional[Path]]:
        """Load a config for read-only scenarios."""
        resolved, stale = self.resolve_config_path(config_path)
        if resolved is None:
            cfg = self.create_default_config()
            platform_cfg, _, _ = self.load_platform_config()
            self.apply_platform_defaults(cfg, platform_cfg)
            return cfg, None, stale

        cfg = self._repo.read_benchmark_config(resolved)
        self._hydrate_config(cfg)
        platform_cfg, _, _ = self.load_platform_config()
        self.apply_platform_defaults(cfg, platform_cfg)
        return cfg, resolved, stale

    def load_for_write(
        self,
        config_path: Optional[Path],
        allow_create: bool = True,
    ) -> Tuple[BenchmarkConfig, Path, Optional[Path], bool]:
        """
        Load a config for mutation and return (config, target_path, stale_pointer, created_new).
        """
        resolved, stale = self.resolve_config_path(config_path)
        target = resolved or self._repo.default_target
        created = False

        if target.exists():
            cfg = self._repo.read_benchmark_config(target)
            self._hydrate_config(cfg)
        else:
            if not allow_create:
                raise FileNotFoundError(f"Config file not found: {target}")
            self._repo.ensure_parent(target)
            cfg = self.create_default_config()
            created = True

        return cfg, target, stale, created

    def add_workload(
        self,
        name: str,
        config: Optional[Path],
        set_default: bool,
    ) -> Tuple[BenchmarkConfig, Path, Optional[Path]]:
        """Add a workload to the run config (ensuring plugin settings)."""
        cfg, target, stale, _ = self.load_for_write(config, allow_create=True)
        registry = create_registry()
        if name not in registry.available():
            raise ValueError(
                f"Plugin '{name}' is not installed. Use `lb plugin list` to see available plugins."
            )

        if name not in cfg.plugin_settings:
            plugin = registry.get(name)
            if hasattr(plugin, "config_cls"):
                cfg.plugin_settings[name] = plugin.config_cls()
        apply_plugin_assets(cfg, registry)

        workload = cfg.workloads.get(name) or WorkloadConfig(plugin=name, options={})
        cfg.workloads[name] = workload

        self._repo.write_benchmark_config(cfg, target)

        if set_default:
            self._repo.write_saved_config_path(target)
        return cfg, target, stale

    def remove_plugin(
        self,
        name: str,
        config: Optional[Path],
    ) -> Tuple[BenchmarkConfig, Path, Optional[Path], bool]:
        """
        Remove a plugin's workload and settings from a config file.

        Returns (config, target_path, stale_pointer, removed_flag).
        """
        cfg, target, stale, _ = self.load_for_write(config, allow_create=False)
        removed = False
        if name in cfg.workloads:
            cfg.workloads.pop(name, None)
            removed = True
        if name in cfg.plugin_settings:
            cfg.plugin_settings.pop(name, None)
            removed = True
        self._repo.write_benchmark_config(cfg, target)
        return cfg, target, stale, removed

    def add_remote_host(
        self,
        host: RemoteHostConfig,
        config: Optional[Path],
        enable_remote: bool = True,
        set_default: bool = False,
    ) -> Tuple[BenchmarkConfig, Path, Optional[Path]]:
        """Add or replace a remote host definition and persist the config."""
        cfg, target, stale, _ = self.load_for_write(config, allow_create=True)
        cfg.remote_hosts = [existing for existing in cfg.remote_hosts if existing.name != host.name]
        cfg.remote_hosts.append(host)
        cfg.remote_execution.enabled = enable_remote
        self._repo.write_benchmark_config(cfg, target)
        if set_default:
            self._repo.write_saved_config_path(target)
        return cfg, target, stale

    def remove_remote_host(
        self,
        name: str,
        config: Optional[Path],
    ) -> Tuple[BenchmarkConfig, Path, Optional[Path], bool]:
        """Remove a remote host by name from the config.

        Returns (config, target_path, stale_pointer, removed_flag).
        """
        cfg, target, stale, _ = self.load_for_write(config, allow_create=False)
        original_count = len(cfg.remote_hosts)
        cfg.remote_hosts = [h for h in cfg.remote_hosts if h.name != name]
        removed = len(cfg.remote_hosts) < original_count

        # Disable remote execution if no hosts remain
        if not cfg.remote_hosts:
            cfg.remote_execution.enabled = False

        self._repo.write_benchmark_config(cfg, target)
        return cfg, target, stale, removed

    def write_saved_config_path(self, path: Path) -> None:
        """Persist a pointer to the preferred config path."""
        self._repo.write_saved_config_path(path)

    def read_saved_config_path(self) -> Tuple[Optional[Path], Optional[Path]]:
        """Return (resolved_path, stale_path) from the pointer file, if any."""
        return self._repo.read_saved_config_path()

    def clear_saved_config_path(self) -> None:
        """Remove the saved config path pointer, if present."""
        self._repo.clear_saved_config_path()
