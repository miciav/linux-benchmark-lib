"""Unit tests for the PTS ramspeed workload plugin."""

import pytest
from lb_plugins.api import (
    PhoronixConfig,
    PhoronixGenerator,
    PhoronixTestSuiteWorkloadPlugin,
    get_phoronix_plugins,
)

pytestmark = pytest.mark.unit_runner


def test_pts_ramspeed_plugin_exists():
    """Verify that the ramspeed plugin is loaded from the YAML."""
    plugins = get_phoronix_plugins()
    ram_plugin = next((p for p in plugins if p.name == "pts_ramspeed"), None)

    assert ram_plugin is not None, "pts_ramspeed plugin not found"
    assert isinstance(ram_plugin, PhoronixTestSuiteWorkloadPlugin)
    assert "RAMspeed" in ram_plugin.description
    assert "memory" in ram_plugin._spec.tags


def test_pts_ramspeed_generator_config():
    """Verify the generator configuration for ramspeed."""
    plugins = get_phoronix_plugins()
    ram_plugin = next((p for p in plugins if p.name == "pts_ramspeed"), None)
    assert ram_plugin is not None

    config = PhoronixConfig()
    generator = ram_plugin.create_generator(config)

    assert isinstance(generator, PhoronixGenerator)
    assert generator.profile == "ramspeed"
    assert "build-essential" in generator.system_packages
    assert generator.expected_runtime_seconds == 120
