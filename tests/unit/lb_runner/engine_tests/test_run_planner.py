"""Unit tests for RunPlanner execution planning."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from lb_plugins.api import WorkloadIntensity, WorkloadPlugin
from lb_runner.api import BenchmarkConfig, WorkloadConfig
from lb_runner.engine.planning import RunPlanner


pytestmark = [pytest.mark.unit, pytest.mark.unit_runner]


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


def _make_planner(tmp_path: Path) -> RunPlanner:
    cfg = BenchmarkConfig(
        output_dir=tmp_path / "out",
        report_dir=tmp_path / "rep",
        data_export_dir=tmp_path / "exp",
    )
    cfg.workloads["dummy"] = WorkloadConfig(plugin="dummy")
    return RunPlanner(
        workloads=cfg.workloads,
        repetitions=cfg.repetitions,
        logger=SimpleNamespace(info=lambda *_: None, warning=lambda *_: None),
    )


class TestRunPlannerRepetitions:
    """Tests for repetition selection logic."""

    def test_select_repetitions_default(self, tmp_path: Path) -> None:
        """Default repetitions returns configured range."""
        planner = _make_planner(tmp_path)
        assert planner.select_repetitions(None, None) == [1, 2, 3]

    def test_select_repetitions_single_override(self, tmp_path: Path) -> None:
        """Single repetition override returns just that repetition."""
        planner = _make_planner(tmp_path)
        assert planner.select_repetitions(2, None) == [2]

    def test_select_repetitions_list_override(self, tmp_path: Path) -> None:
        """List override returns specified repetitions."""
        planner = _make_planner(tmp_path)
        assert planner.select_repetitions(None, [4, 5]) == [4, 5]

    def test_select_repetitions_rejects_zero(self, tmp_path: Path) -> None:
        """Repetition 0 is rejected."""
        planner = _make_planner(tmp_path)
        with pytest.raises(ValueError):
            planner.select_repetitions(None, [0])


class TestRunPlannerConfigResolution:
    """Tests for workload config resolution."""

    def test_resolve_config_input_prefers_preset(self, tmp_path: Path) -> None:
        """Preset config is used when intensity is specified."""
        planner = _make_planner(tmp_path)
        wl_cfg = WorkloadConfig(plugin="dummy", intensity="low")
        plugin = DummyPlugin(preset={"preset": True})
        resolved = planner.resolve_config_input(wl_cfg, plugin)
        assert resolved == {"preset": True}
