"""Characterization tests for LocalRunner execution flow."""

from __future__ import annotations

import json

import pytest

from lb_runner.api import BenchmarkConfig, LocalRunner, WorkloadConfig

pytestmark = pytest.mark.unit_runner


class DummyGenerator:
    def __init__(self) -> None:
        self._is_running = False

    def prepare(self) -> None:
        return None

    def start(self) -> None:
        self._is_running = False

    def stop(self) -> None:
        self._is_running = False

    def get_result(self) -> dict[str, int]:
        return {"returncode": 0}


class DummyPlugin:
    name = "dummy"

    def get_preset_config(self, _level):
        return None

    def export_results_to_csv(self, *_, **__):
        return []


class DummyRegistry:
    def __init__(self, plugin: DummyPlugin, generator: DummyGenerator) -> None:
        self._plugin = plugin
        self._generator = generator

    def get(self, _name: str) -> DummyPlugin:
        return self._plugin

    def create_generator(self, _plugin_name: str, _config_input):
        return self._generator

    def create_collectors(self, _config: BenchmarkConfig):
        return []


def test_local_runner_writes_results(tmp_path, monkeypatch):
    cfg = BenchmarkConfig(
        output_dir=tmp_path / "out",
        report_dir=tmp_path / "rep",
        data_export_dir=tmp_path / "exp",
        workloads={"dummy": WorkloadConfig(plugin="dummy", enabled=True)},
        warmup_seconds=0,
        cooldown_seconds=0,
        collect_system_info=False,
        test_duration_seconds=1,
    )
    plugin = DummyPlugin()
    generator = DummyGenerator()
    registry = DummyRegistry(plugin, generator)

    monkeypatch.setattr(LocalRunner, "_pre_test_cleanup", lambda _self: None)

    runner = LocalRunner(cfg, registry=registry)
    run_id = "run-characterization"

    success = runner.run_benchmark(
        "dummy",
        repetition_override=1,
        total_repetitions=1,
        run_id=run_id,
    )

    results_path = cfg.output_dir / run_id / "dummy" / "dummy_results.json"
    assert success is True
    assert results_path.exists()

    data = json.loads(results_path.read_text(encoding="utf-8"))
    assert data[0]["repetition"] == 1
    assert data[0]["generator_result"]["returncode"] == 0
