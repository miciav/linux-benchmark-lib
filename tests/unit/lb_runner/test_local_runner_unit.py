"""Unit tests for LocalRunner dependency injection."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from lb_plugins.api import PluginRegistry, builtin_plugins
from lb_runner.api import BenchmarkConfig, LocalRunner, WorkloadConfig
from lb_runner.models.config import LokiConfig

pytestmark = pytest.mark.unit_runner


def test_local_runner_requires_registry(tmp_path: Path) -> None:
    """LocalRunner should rely on an injected registry, not a hidden default."""
    cfg = BenchmarkConfig(
        output_dir=tmp_path / "out",
        report_dir=tmp_path / "rep",
        data_export_dir=tmp_path / "exp",
    )
    registry = PluginRegistry(builtin_plugins())

    runner = LocalRunner(cfg, registry=registry)
    assert runner.plugin_registry.get("stress_ng") is registry.get("stress_ng")

    with pytest.raises(TypeError):
        LocalRunner(cfg)  # type: ignore[call-arg]


def test_local_runner_merges_results_across_repetition_override_calls(
    tmp_path: Path,
) -> None:
    cfg = BenchmarkConfig(
        output_dir=tmp_path / "out",
        report_dir=tmp_path / "rep",
        data_export_dir=tmp_path / "exp",
        workloads={"dummy": WorkloadConfig(plugin="stress_ng")},
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
    assert runner1.run_benchmark(
        "dummy", repetition_override=1, total_repetitions=2, run_id=run_id
    )

    runner2 = LocalRunner(cfg, registry=registry)
    assert runner2.run_benchmark(
        "dummy", repetition_override=2, total_repetitions=2, run_id=run_id
    )

    results_path = cfg.output_dir / run_id / "dummy" / "dummy_results.json"
    data = json.loads(results_path.read_text(encoding="utf-8"))
    assert [entry.get("repetition") for entry in data] == [1, 2]


def test_local_runner_attaches_and_detaches_handlers(tmp_path: Path) -> None:
    """LocalRunner should attach log handlers during run preparation."""
    cfg = BenchmarkConfig(
        output_dir=tmp_path / "out",
        report_dir=tmp_path / "rep",
        data_export_dir=tmp_path / "exp",
        loki=LokiConfig(enabled=True, endpoint="http://loki"),
    )
    registry = MagicMock()
    runner = LocalRunner(cfg, registry=registry)
    mock_attach = MagicMock()
    mock_sync = MagicMock()
    runner._log_manager.attach = mock_attach
    runner._log_manager.sync_loki_env = mock_sync

    runner._prepare_run_scope("run-1", workload="test", repetition=1, phase="setup")

    assert mock_sync.called
    assert mock_attach.called
