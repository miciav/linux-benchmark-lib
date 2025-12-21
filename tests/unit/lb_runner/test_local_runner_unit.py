"""Unit tests for LocalRunner dependency injection."""

import json
from unittest.mock import MagicMock

import pytest

from lb_runner.benchmark_config import BenchmarkConfig, WorkloadConfig
from lb_runner.local_runner import LocalRunner
from lb_runner.plugin_system.builtin import builtin_plugins
from lb_runner.plugin_system.registry import PluginRegistry

pytestmark = pytest.mark.unit_runner



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


def test_local_runner_merges_results_across_repetition_override_calls(tmp_path):
    cfg = BenchmarkConfig(
        output_dir=tmp_path / "out",
        report_dir=tmp_path / "rep",
        data_export_dir=tmp_path / "exp",
        workloads={"dummy": WorkloadConfig(plugin="stress_ng", enabled=True)},
        warmup_seconds=0,
        cooldown_seconds=0,
        collect_system_info=False,
    )

    plugin = MagicMock()
    plugin.name = "stress_ng"
    plugin.export_results_to_csv.return_value = []

    registry = MagicMock()
    registry.get.return_value = plugin
    registry.create_collectors.return_value = []

    generator = MagicMock()
    generator.get_result.return_value = {"returncode": 0}
    generator._is_running = False
    registry.create_generator.return_value = generator

    run_id = "run-merge-test"

    runner1 = LocalRunner(cfg, registry=registry)
    assert runner1.run_benchmark("dummy", repetition_override=1, total_repetitions=2, run_id=run_id)

    runner2 = LocalRunner(cfg, registry=registry)
    assert runner2.run_benchmark("dummy", repetition_override=2, total_repetitions=2, run_id=run_id)

    results_path = cfg.output_dir / run_id / "dummy" / "dummy_results.json"
    data = json.loads(results_path.read_text(encoding="utf-8"))
    assert [entry.get("repetition") for entry in data] == [1, 2]
