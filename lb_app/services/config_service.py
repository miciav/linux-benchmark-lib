"""Configuration resolution and mutation helpers for the CLI."""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import asdict, is_dataclass
from inspect import isclass
from pathlib import Path
from typing import Any, Optional, Tuple

from pydantic import BaseModel, ValidationError

from lb_controller.api import (
    BenchmarkConfig,
    RemoteHostConfig,
    WorkloadConfig,
    apply_playbook_defaults,
)
from lb_plugins.api import PluginRegistry, apply_plugin_assets, create_registry

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_NAME = "config.json"
DEFAULT_CONFIG_POINTER = "config_path"


def _resolve_registry(registry: PluginRegistry | None) -> PluginRegistry:
    return registry or create_registry()


def hydrate_plugin_settings(
    config: BenchmarkConfig,
    registry: PluginRegistry | None = None,
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
    config: BenchmarkConfig,
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
    config: BenchmarkConfig,
    dump_mode: str | None = None,
    convert_dataclasses: bool = False,
) -> None:
    """Populate workloads dict from plugin_settings if not explicitly defined."""
    if not config.plugin_settings:
        return

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
        registry = create_registry()
        hydrate_plugin_settings(cfg, registry=registry)
        apply_plugin_assets(cfg, registry)
        apply_playbook_defaults(cfg)

    def create_default_config(self) -> BenchmarkConfig:
        """Create a fresh BenchmarkConfig populated with all installed plugins."""
        registry = create_registry()
        cfg = BenchmarkConfig()
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
        apply_plugin_assets(cfg, registry)

        for name in available:
            if name not in cfg.workloads:
                cfg.workloads[name] = WorkloadConfig(plugin=name, enabled=False)

        apply_playbook_defaults(cfg)
        return cfg

    def load_for_read(self, config_path: Optional[Path]) -> Tuple[BenchmarkConfig, Optional[Path], Optional[Path]]:
        """Load a config for read-only scenarios."""
        resolved, stale = self.resolve_config_path(config_path)
        if resolved is None:
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

        if enabled:
            registry = create_registry()
            if name not in registry.available():
                raise ValueError(f"Plugin '{name}' is not installed. Use `lb plugin list` to see available plugins.")

            if name not in cfg.plugin_settings:
                plugin = registry.get(name)
                if hasattr(plugin, "config_cls"):
                    cfg.plugin_settings[name] = plugin.config_cls()
            apply_plugin_assets(cfg, registry)

        workload = cfg.workloads.get(name) or WorkloadConfig(plugin=name, options={})
        workload.enabled = enabled
        cfg.workloads[name] = workload

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

    def _read_saved_config_path(self) -> Tuple[Optional[Path], Optional[Path]]:
        """Return (resolved_path, stale_path) from the pointer file, if any."""
        if not self.pointer.exists():
            return None, None
        try:
            text = self.pointer.read_text().strip()
        except Exception:
            return None, None
        if not text:
            return None, None
        path = Path(text).expanduser()
        if path.exists():
            return path, None
        return None, path
