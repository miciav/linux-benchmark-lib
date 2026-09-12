"""Tests for the interactive workload selection flow."""

from pathlib import Path

import pytest

from lb_app.api import BenchmarkConfig, ConfigService, PluginRegistry, WorkloadConfig
from lb_ui.flows import selection as selection_mod
from lb_ui.flows.selection import select_workloads_interactively

pytestmark = pytest.mark.unit_ui


class _FakePicker:
    """Returns the chosen workload's selected *variant*, like the real picker."""

    def __init__(self, workload: str, variant_index: int = 2) -> None:
        self.workload = workload
        self.variant_index = variant_index
        self.seen_items = []

    def pick_many(self, items, title=None):
        self.seen_items = list(items)
        for item in items:
            if item.id == self.workload:
                return [item.variants[self.variant_index]]
        raise AssertionError(
            f"item {self.workload!r} not offered: {[i.id for i in items]}"
        )


class _FakeUI:
    def __init__(self, picker) -> None:
        self.picker = picker
        self.present = _FakePresent()


class _FakePresent:
    def warning(self, *_a, **_k):
        return None

    def success(self, *_a, **_k):
        return None

    def info(self, *_a, **_k):
        return None

    def error(self, *_a, **_k):
        return None


def test_picking_a_workload_records_its_name(monkeypatch, tmp_path: Path):
    """Picking a workload must record its name, not the intensity label.

    Picking "stream" with the medium variant must keep the workload named
    "stream" and set its intensity, not create a workload called "medium".
    """
    monkeypatch.setattr(selection_mod, "is_tty_available", lambda: True)
    config_service = ConfigService()

    cfg_path = tmp_path / "cfg.json"
    cfg = BenchmarkConfig()
    cfg.workloads["stream"] = WorkloadConfig(plugin="stream", options={})
    cfg.save(cfg_path)

    ui = _FakeUI(_FakePicker("stream"))
    registry = PluginRegistry()

    select_workloads_interactively(
        ui, config_service, cfg, registry, cfg_path, set_default=False
    )

    saved = BenchmarkConfig.load(cfg_path)
    assert "stream" in saved.workloads, sorted(saved.workloads)
    assert "medium" not in saved.workloads, sorted(saved.workloads)
    assert saved.workloads["stream"].intensity == "medium"
