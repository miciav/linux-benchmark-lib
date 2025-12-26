from pathlib import Path
from types import SimpleNamespace

import pytest

from lb_plugins.api import WorkloadIntensity, WorkloadPlugin
from lb_runner.api import BenchmarkConfig, LocalRunner, WorkloadConfig


class DummyPlugin(WorkloadPlugin):
    def __init__(self, preset=None):
        self._preset = preset

    @property
    def name(self) -> str:  # pragma: no cover - unused in tests
        return "dummy"

    @property
    def description(self) -> str:  # pragma: no cover - unused in tests
        return ""

    @property
    def config_cls(self):  # pragma: no cover - unused
        return SimpleNamespace

    def create_generator(self, config):
        return SimpleNamespace()

    def get_preset_config(self, level: WorkloadIntensity):
        return self._preset if level == WorkloadIntensity.LOW else None


def _make_runner(tmp_path: Path) -> LocalRunner:
    cfg = BenchmarkConfig(
        output_dir=tmp_path / "out",
        report_dir=tmp_path / "rep",
        data_export_dir=tmp_path / "exp",
    )
    cfg.workloads["dummy"] = WorkloadConfig(plugin="dummy", enabled=True)
    runner = LocalRunner(config=cfg, registry=SimpleNamespace(create_generator=lambda *_: SimpleNamespace()))
    return runner


def test_select_repetitions_validates(tmp_path: Path) -> None:
    runner = _make_runner(tmp_path)
    assert runner._select_repetitions(None, None) == [1, 2, 3]
    assert runner._select_repetitions(2, None) == [2]
    assert runner._select_repetitions(None, [4, 5]) == [4, 5]
    with pytest.raises(ValueError):
        runner._select_repetitions(None, [0])


def test_merge_results_overwrites_repetition(tmp_path: Path) -> None:
    runner = _make_runner(tmp_path)
    results_file = tmp_path / "out.json"
    existing = [{"repetition": 1, "value": "old"}, {"repetition": 2, "value": "keep"}]
    results_file.write_text('[{"repetition": 1, "value": "old"}, {"repetition": 2, "value": "keep"}]')
    merged = runner._merge_results(results_file, [{"repetition": 1, "value": "new"}])
    assert any(r["value"] == "new" for r in merged)
    assert any(r["value"] == "keep" for r in merged)


def test_resolve_config_input_prefers_preset(tmp_path: Path) -> None:
    runner = _make_runner(tmp_path)
    wl_cfg = WorkloadConfig(plugin="dummy", enabled=True, intensity="low")
    plugin = DummyPlugin(preset={"preset": True})
    resolved = runner._resolve_config_input(wl_cfg, plugin)
    assert resolved == {"preset": True}
