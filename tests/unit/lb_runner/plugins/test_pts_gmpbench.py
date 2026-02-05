"""Unit tests for the PTS gmpbench workload plugin."""

import pytest
from lb_plugins.api import (
    PhoronixConfig,
    PhoronixGenerator,
    PhoronixTestSuiteWorkloadPlugin,
    get_phoronix_plugins,
)

pytestmark = pytest.mark.unit_runner


def test_pts_gmpbench_plugin_exists():
    """Verify that the gmpbench plugin is loaded from the YAML."""
    plugins = get_phoronix_plugins()
    gmp_plugin = next((p for p in plugins if p.name == "pts_gmpbench"), None)

    assert gmp_plugin is not None, "pts_gmpbench plugin not found"
    assert isinstance(gmp_plugin, PhoronixTestSuiteWorkloadPlugin)
    assert "GMPbench" in gmp_plugin.description
    assert "math" in gmp_plugin._spec.tags


def test_pts_gmpbench_generator_config():
    """Verify the generator configuration for gmpbench."""
    plugins = get_phoronix_plugins()
    gmp_plugin = next((p for p in plugins if p.name == "pts_gmpbench"), None)
    assert gmp_plugin is not None

    config = PhoronixConfig()
    generator = gmp_plugin.create_generator(config)

    assert isinstance(generator, PhoronixGenerator)
    assert generator.profile == "gmpbench"
    assert "build-essential" in generator.system_packages
    assert "m4" in generator.system_packages
    assert generator.expected_runtime_seconds == 300
