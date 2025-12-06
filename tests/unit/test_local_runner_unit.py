"""Unit tests for LocalRunner dependency injection."""

import pytest

from lb_runner.benchmark_config import BenchmarkConfig
from lb_runner.local_runner import LocalRunner
from lb_runner.plugin_system.builtin import builtin_plugins
from lb_runner.plugin_system.registry import PluginRegistry


def test_local_runner_requires_registry(tmp_path):
    """LocalRunner should rely on an injected registry, not a hidden default."""
    cfg = BenchmarkConfig(
        output_dir=tmp_path / "out",
        report_dir=tmp_path / "rep",
        data_export_dir=tmp_path / "exp",
    )
    registry = PluginRegistry(builtin_plugins())

    runner = LocalRunner(cfg, registry=registry)
    assert runner.plugin_registry is registry

    with pytest.raises(TypeError):
        LocalRunner(cfg)  # type: ignore[misc]
