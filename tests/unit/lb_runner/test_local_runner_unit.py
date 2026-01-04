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


def test_local_runner_merges_results_across_repetition_override_calls(tmp_path: Path) -> None:
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
    assert runner1.run_benchmark("dummy", repetition_override=1, total_repetitions=2, run_id=run_id)

    runner2 = LocalRunner(cfg, registry=registry)
    assert runner2.run_benchmark("dummy", repetition_override=2, total_repetitions=2, run_id=run_id)

    results_path = cfg.output_dir / run_id / "dummy" / "dummy_results.json"
    data = json.loads(results_path.read_text(encoding="utf-8"))
    assert [entry.get("repetition") for entry in data] == [1, 2]


def test_local_runner_attaches_and_detaches_handlers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """LocalRunner should attach log handlers during run preparation."""
    cfg = BenchmarkConfig(
        output_dir=tmp_path / "out",
        report_dir=tmp_path / "rep",
        data_export_dir=tmp_path / "exp",
        loki=LokiConfig(enabled=True, endpoint="http://loki"),
    )
    registry = MagicMock()
    runner = LocalRunner(cfg, registry=registry)

    mock_attach_jsonl = MagicMock()
    mock_attach_loki = MagicMock()
    mock_logger = MagicMock()
    mock_get_logger = MagicMock(return_value=mock_logger)

    monkeypatch.setattr("lb_runner.engine.runner.attach_jsonl_handler", mock_attach_jsonl)
    monkeypatch.setattr("lb_runner.engine.runner.attach_loki_handler", mock_attach_loki)
    monkeypatch.setattr("logging.getLogger", mock_get_logger)

    # Test attachment
    runner._prepare_run_scope("run-1", workload="test", repetition=1, phase="setup")
    
    assert mock_attach_jsonl.called
    assert mock_attach_loki.called
    assert runner._jsonl_handler is mock_attach_jsonl.return_value
    assert runner._loki_handler is mock_attach_loki.return_value

    # Test detachment/replacement (calling again)
    old_jsonl = mock_attach_jsonl.return_value
    old_loki = mock_attach_loki.return_value
    
    runner._prepare_run_scope("run-1", workload="test", repetition=2, phase="run")
    
    # Verify old handlers were removed (not directly removed from logger in mock, 
    # but close() called if we mock handlers properly, but runner checks if self._handler exists)
    # Actually LocalRunner calls: logging.getLogger().removeHandler(self._jsonl_handler)
    # but mock_get_logger returns a mock which we can check.
    
    mock_logger.removeHandler.assert_any_call(old_jsonl)
    mock_logger.removeHandler.assert_any_call(old_loki)
    
    # And new ones attached
    assert mock_attach_jsonl.call_count == 2
    assert mock_attach_loki.call_count == 2
