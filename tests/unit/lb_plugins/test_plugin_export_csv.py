from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from lb_plugins.api import WorkloadPlugin
from lb_runner.api import BenchmarkConfig, LocalRunner, WorkloadConfig

pytestmark = [pytest.mark.unit_runner, pytest.mark.unit_plugins]



class DummyPlugin(WorkloadPlugin):
    """Minimal plugin that records export invocations."""

    def __init__(self) -> None:
        self.export_called: dict[str, Any] | None = None

    @property
    def name(self) -> str:
        return "dummy"

    @property
    def description(self) -> str:
        return "dummy plugin"

    @property
    def config_cls(
    ):
        @dataclass
        class _Cfg:
            pass

        return _Cfg

    def create_generator(self, config: Any) -> Any:  # pragma: no cover - not used in this test
        return MagicMock()

    def export_results_to_csv(self, results, output_dir: Path, run_id: str, test_name: str):
        self.export_called = {
            "results": results,
            "output_dir": output_dir,
            "run_id": run_id,
            "test_name": test_name,
        }
        csv_path = output_dir / f"{test_name}_plugin.csv"
        csv_path.write_text("repetition,success\n1,True\n", encoding="utf-8")
        return [csv_path]


class DummyRegistry:
    def __init__(self, plugin: WorkloadPlugin) -> None:
        self._plugin = plugin

    def get(self, name: str) -> WorkloadPlugin:
        return self._plugin

    def create_generator(self, name: str, cfg: Any) -> Any:
        return MagicMock()

    def create_collectors(self, cfg: BenchmarkConfig):
        return []


def test_plugin_export_hook_writes_csv(monkeypatch, tmp_path):
    cfg = BenchmarkConfig(
        repetitions=1,
        output_dir=tmp_path / "out",
        report_dir=tmp_path / "rep",
        data_export_dir=tmp_path / "exp",
        workloads={"dummy": WorkloadConfig(plugin="dummy")},
    )
    plugin = DummyPlugin()
    registry = DummyRegistry(plugin)
    runner = LocalRunner(cfg, registry=registry)

    # Mock RepetitionExecutor instead of _run_single_test
    with patch("lb_runner.engine.runner.RepetitionExecutor") as MockExecutor:
        instance = MockExecutor.return_value
        instance.execute.return_value = {
            "test_name": "dummy",
            "repetition": 1,
            "start_time": None,
            "end_time": None,
            "duration_seconds": 1.0,
            "generator_result": {"returncode": 0},
            "metrics": {},
            "success": True,
        }

        runner.run_benchmark("dummy", run_id="run-1")

    output_dir = cfg.output_dir / "run-1" / "dummy"
    csv_path = output_dir / "dummy_plugin.csv"
    assert csv_path.exists()
    assert plugin.export_called is not None
    assert plugin.export_called["run_id"] == "run-1"