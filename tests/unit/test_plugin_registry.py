"""Tests for the workload plugin registry."""

from dataclasses import dataclass

import importlib.metadata
import pytest

from linux_benchmark_lib.plugin_system.registry import PluginRegistry
from linux_benchmark_lib.plugin_system.interface import WorkloadPlugin
from linux_benchmark_lib.plugin_system.base_generator import BaseGenerator


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
    # ensure registry is still usable
    assert registry.available() == {}
    assert any("Failed to load plugin entry point" in message for message in caplog.messages)
