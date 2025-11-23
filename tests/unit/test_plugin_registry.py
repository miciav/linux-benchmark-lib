"""Tests for the workload plugin registry."""

from dataclasses import dataclass

from plugins.registry import PluginRegistry, WorkloadPlugin
from workload_generators._base_generator import BaseGenerator


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


def test_registry_creates_generator_from_plugin():
    """Plugin registry should instantiate generators with provided options."""
    plugin = WorkloadPlugin(
        name="dummy",
        description="Test plugin",
        config_cls=DummyConfig,
        factory=DummyGenerator,
    )

    registry = PluginRegistry(plugins=[plugin])
    generator = registry.create_generator("dummy", {"flag": True})

    assert isinstance(generator, DummyGenerator)
    assert generator.config.flag is True
