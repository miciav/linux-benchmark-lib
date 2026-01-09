"""File-system repository for configuration assets."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple

from lb_controller.api import BenchmarkConfig, PlatformConfig

DEFAULT_CONFIG_NAME = "config.json"
DEFAULT_CONFIG_POINTER = "config_path"
PLATFORM_CONFIG_NAME = "platform.json"


class ConfigRepository:
    """Persist and resolve config files in the local filesystem."""

    def __init__(self, config_home: Optional[Path] = None) -> None:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        base = Path(xdg) if xdg else Path.home() / ".config"
        self.config_home = (config_home or base) / "lb"
        self.default_target = self.config_home / DEFAULT_CONFIG_NAME
        self.pointer = self.config_home / DEFAULT_CONFIG_POINTER
        self.platform_target = self.config_home / PLATFORM_CONFIG_NAME

    def ensure_home(self) -> None:
        self.config_home.mkdir(parents=True, exist_ok=True)

    def ensure_parent(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)

    def resolve_config_path(
        self, config_path: Optional[Path]
    ) -> Tuple[Optional[Path], Optional[Path]]:
        if config_path is not None:
            return Path(config_path).expanduser(), None

        env_path = os.environ.get("LB_CONFIG_PATH")
        if env_path:
            return Path(env_path), None

        saved, stale = self.read_saved_config_path()
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

    def read_saved_config_path(self) -> Tuple[Optional[Path], Optional[Path]]:
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

    def write_saved_config_path(self, path: Path) -> None:
        self.ensure_home()
        self.pointer.write_text(str(path.expanduser()))

    def clear_saved_config_path(self) -> None:
        if self.pointer.exists():
            self.pointer.unlink()

    def read_benchmark_config(self, path: Path) -> BenchmarkConfig:
        return BenchmarkConfig.load(path)

    def write_benchmark_config(self, cfg: BenchmarkConfig, path: Path) -> None:
        cfg.save(path)

    def read_platform_config(self) -> PlatformConfig | None:
        if self.platform_target.exists():
            return PlatformConfig.load(self.platform_target)
        return None

    def write_platform_config(self, cfg: PlatformConfig, path: Path | None = None) -> Path:
        target = path or self.platform_target
        self.ensure_home()
        cfg.save(target)
        return target
