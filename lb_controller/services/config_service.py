"""Configuration resolution and mutation helpers for the CLI."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional, Tuple, Any

from lb_runner.benchmark_config import BenchmarkConfig, RemoteHostConfig, WorkloadConfig


DEFAULT_CONFIG_NAME = "config.json"
DEFAULT_CONFIG_POINTER = "config_path"


class ConfigService:
    """Resolve, load, and mutate BenchmarkConfig files."""

    def __init__(self, config_home: Optional[Path] = None) -> None:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        base = Path(xdg) if xdg else Path.home() / ".config"
        self.config_home = (config_home or base) / "lb"
        self.default_target = self.config_home / DEFAULT_CONFIG_NAME
        self.pointer = self.config_home / DEFAULT_CONFIG_POINTER

    def ensure_home(self) -> None:
        """Create the config home directory."""
        self.config_home.mkdir(parents=True, exist_ok=True)

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
        if config_path is not None:
            return Path(config_path).expanduser(), None

        env_path = os.environ.get("LB_CONFIG_PATH")
        if env_path:
            return Path(env_path), None

        saved, stale = self._read_saved_config_path()
        if saved:
            return saved, None
        if stale:
            return None, stale

        local = Path("benchmark_config.json")
        if local.exists():
            return local, None
        if self.default_target.exists():
            return self.default_target, None
        return None, None

    def _hydrate_config(self, cfg: BenchmarkConfig) -> None:
        """
        Convert raw dictionary configs in plugin_settings to Typed Config Objects.
        This requires looking up the plugin definition in the registry.
        """
        # Import here to avoid circular dependency with services package
        from .plugin_service import create_registry
        from lb_runner.plugin_system.settings import hydrate_plugin_settings

        registry = create_registry()
        hydrate_plugin_settings(cfg, registry=registry)
    
    def create_default_config(self) -> BenchmarkConfig:
        """Create a fresh BenchmarkConfig populated with all installed plugins."""
        from .plugin_service import create_registry
        from lb_runner.plugin_system.settings import (
            ensure_workloads_from_plugin_settings,
            populate_default_plugin_settings,
        )

        registry = create_registry()
        
        cfg = BenchmarkConfig()
        # Clear any legacy hardcoded defaults if BenchmarkConfig still has them (redundant safety)
        cfg.workloads = {} 
        cfg.plugin_settings = {}

        available = registry.available(load_entrypoints=True)
        populate_default_plugin_settings(
            cfg,
            registry=registry,
            load_entrypoints=True,
            allow_dataclasses=True,
        )
        ensure_workloads_from_plugin_settings(
            cfg, dump_mode="json", convert_dataclasses=True
        )

        for name, plugin in available.items():
            if name not in cfg.workloads:
                cfg.workloads[name] = WorkloadConfig(plugin=name, enabled=False)
                
        return cfg

    def load_for_read(self, config_path: Optional[Path]) -> Tuple[BenchmarkConfig, Optional[Path], Optional[Path]]:
        """Load a config for read-only scenarios."""
        resolved, stale = self.resolve_config_path(config_path)
        if resolved is None:
            # Fallback to creating a default one in memory if none exists on disk?
            # Or return empty? Current behavior was "using built-in defaults".
            # Let's use our dynamic defaults.
            return self.create_default_config(), None, stale
        
        cfg = BenchmarkConfig.load(resolved)
        self._hydrate_config(cfg)
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
        target = resolved or self.default_target
        created = False

        if target.exists():
            cfg = BenchmarkConfig.load(target)
            self._hydrate_config(cfg)
        else:
            if not allow_create:
                raise FileNotFoundError(f"Config file not found: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            cfg = self.create_default_config()
            created = True

        return cfg, target, stale, created

    def update_workload_enabled(
        self,
        name: str,
        enabled: bool,
        config: Optional[Path],
        set_default: bool,
    ) -> Tuple[BenchmarkConfig, Path, Optional[Path]]:
        """Enable/disable workload and persist the config."""
        cfg, target, stale, _ = self.load_for_write(config, allow_create=True)
        
        # Enforce that the plugin exists if we are enabling it
        if enabled:
            from .plugin_service import create_registry

            registry = create_registry()
            if name not in registry.available():
                raise ValueError(f"Plugin '{name}' is not installed. Use `lb plugin list` to see available plugins.")

            # Initialize default config if missing
            if name not in cfg.plugin_settings:
                plugin = registry.get(name)
                if hasattr(plugin, 'config_cls'):
                    cfg.plugin_settings[name] = plugin.config_cls()

        workload = cfg.workloads.get(name) or WorkloadConfig(plugin=name, options={})
        workload.enabled = enabled
        cfg.workloads[name] = workload
        
        # Save will serialize the config objects back to dicts/json automatically
        cfg.save(target)
        
        if set_default:
            self.write_saved_config_path(target)
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
        cfg.save(target)
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
        cfg.save(target)
        if set_default:
            self.write_saved_config_path(target)
        return cfg, target, stale

    def write_saved_config_path(self, path: Path) -> None:
        """Persist a pointer to the preferred config path."""
        self.ensure_home()
        self.pointer.write_text(str(path.expanduser()))

    def read_saved_config_path(self) -> Tuple[Optional[Path], Optional[Path]]:
        """Public wrapper returning (valid_path, stale_path)."""
        return self._read_saved_config_path()

    def clear_saved_config_path(self) -> None:
        """Remove the stored config pointer."""
        if self.pointer.exists():
            self.pointer.unlink()

    def _read_saved_config_path(self) -> Tuple[Optional[Path], Optional[Path]]:
        """Return (valid_path, stale_path)."""
        if not self.pointer.exists():
            return None, None

        raw = self.pointer.read_text().strip()
        if not raw:
            return None, None

        candidate = Path(raw).expanduser()
        if candidate.exists():
            return candidate, None
        return None, candidate
