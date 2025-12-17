"""Tests for the workload plugin registry."""

from dataclasses import dataclass

import importlib.metadata
import pytest

from lb_runner.plugin_system import registry as registry_mod
from lb_runner.plugin_system.registry import PluginRegistry, resolve_user_plugin_dir
from lb_runner.plugin_system.interface import WorkloadPlugin
from lb_runner.plugin_system.base_generator import BaseGenerator

pytestmark = [pytest.mark.unit, pytest.mark.plugins]



@dataclass
class DummyConfig:
    """Simple config for test plugin."""

    flag: bool = False


class DummyGenerator(BaseGenerator):
    """Minimal generator used for plugin tests."""

    def __init__(self, config: DummyConfig):
        super().__init__("dummy")
        self.config = config

    def _run_command(self) -> None:
        self._result = {"flag": self.config.flag}
        self._is_running = False

    def _validate_environment(self) -> bool:
        return True

    def _stop_workload(self) -> None:
        pass


def test_registry_creates_generator_from_plugin():
    """Plugin registry should instantiate generators with provided options."""
    class DummyPlugin(WorkloadPlugin):
        @property
        def name(self) -> str:
            return "dummy"

        @property
        def description(self) -> str:
            return "Test plugin"

        @property
        def config_cls(self):
            return DummyConfig

        def create_generator(self, config: DummyConfig) -> DummyGenerator:
            return DummyGenerator(config)

    plugin = DummyPlugin()

    registry = PluginRegistry(plugins=[plugin])
    generator = registry.create_generator("dummy", {"flag": True})

    assert isinstance(generator, DummyGenerator)
    assert generator.config.flag is True


def test_registry_logs_entrypoint_failures(monkeypatch, caplog):
    """Registry should emit a warning when an entry point fails to load."""

    class DummyEntryPoint:
        name = "broken"

        def load(self):
            raise RuntimeError("boom")

    class DummyEntryPoints:
        def select(self, group):
            return [DummyEntryPoint()]

    monkeypatch.setattr(importlib.metadata, "entry_points", lambda: DummyEntryPoints())

    caplog.set_level("WARNING")
    registry = PluginRegistry()
    registry.available(load_entrypoints=True)  # trigger loading
    assert any("Failed to load plugin entry point" in message for message in caplog.messages)


def test_resolve_user_plugin_dir_env_override(monkeypatch, tmp_path):
    """Env override should take precedence for user plugin directory."""
    override = tmp_path / "custom_plugins"
    monkeypatch.setenv("LB_USER_PLUGIN_DIR", str(override))
    resolved = resolve_user_plugin_dir()
    assert resolved == override.resolve()


def test_resolve_user_plugin_dir_prefers_builtin_root(monkeypatch, tmp_path):
    """When writable, user plugins live under package plugins/_user."""
    builtin_root = tmp_path / "builtin_plugins"
    legacy_root = tmp_path / "legacy_plugins"
    monkeypatch.delenv("LB_USER_PLUGIN_DIR", raising=False)
    monkeypatch.setattr(registry_mod, "BUILTIN_PLUGIN_ROOT", builtin_root)
    monkeypatch.setattr(registry_mod, "LEGACY_USER_PLUGIN_DIR", legacy_root)

    resolved = resolve_user_plugin_dir()
    assert resolved == (builtin_root / "_user").resolve()
    assert resolved.exists()


def test_registry_loads_user_module_get_plugins(monkeypatch, tmp_path):
    """Registry should load multiple plugins from a user module get_plugins()."""
    monkeypatch.setenv("LB_USER_PLUGIN_DIR", str(tmp_path))

    plugin_file = tmp_path / "multi.py"
    plugin_file.write_text(
        """
from lb_runner.plugin_system.interface import WorkloadPlugin, BasePluginConfig


class P1(WorkloadPlugin):
    @property
    def name(self) -> str:
        return "p1"

    @property
    def description(self) -> str:
        return "plugin 1"

    @property
    def config_cls(self):
        return BasePluginConfig

    def create_generator(self, config):
        return object()


class P2(P1):
    @property
    def name(self) -> str:
        return "p2"

    @property
    def description(self) -> str:
        return "plugin 2"


def get_plugins():
    return [P1(), P2()]
""".lstrip()
    )

    registry = PluginRegistry()
    assert "p1" in registry.available()
    assert "p2" in registry.available()


def test_registry_loads_user_module_plugins_list(monkeypatch, tmp_path):
    """Registry should load multiple plugins from a user module PLUGINS list."""
    monkeypatch.setenv("LB_USER_PLUGIN_DIR", str(tmp_path))

    plugin_file = tmp_path / "multi_list.py"
    plugin_file.write_text(
        """
from lb_runner.plugin_system.interface import WorkloadPlugin, BasePluginConfig


class P1(WorkloadPlugin):
    @property
    def name(self) -> str:
        return "p1_list"

    @property
    def description(self) -> str:
        return "plugin 1"

    @property
    def config_cls(self):
        return BasePluginConfig

    def create_generator(self, config):
        return object()


class P2(P1):
    @property
    def name(self) -> str:
        return "p2_list"


PLUGINS = [P1(), P2()]
""".lstrip()
    )

    registry = PluginRegistry()
    assert "p1_list" in registry.available()
    assert "p2_list" in registry.available()
