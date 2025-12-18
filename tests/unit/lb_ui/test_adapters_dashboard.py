"""Tests for UI adapters and dashboard behaviors (non-visual)."""

from types import SimpleNamespace

import pytest

from lb_ui.ui.dashboard import RunDashboard, NoopDashboard
from lb_ui.ui.adapters.headless import HeadlessUIAdapter
from lb_controller.journal import RunJournal


pytestmark = pytest.mark.ui


def _fake_journal():
    cfg = SimpleNamespace(remote_hosts=[SimpleNamespace(name="localhost")], repetitions=1, workloads={"w": {}})
    journal = RunJournal.initialize("run-1", cfg, ["w"])
    return journal


def test_dashboard_log_slicing_respects_height(monkeypatch):
    journal = _fake_journal()
    plan = [{"name": "w", "plugin": "stress_ng", "intensity": "low"}]
    dash = RunDashboard(console=SimpleNamespace(size=SimpleNamespace(height=20, width=80)), plan_rows=plan, journal=journal)  # type: ignore[arg-type]
    # Simulate many logs
    for i in range(50):
        dash.add_log(f"log {i}")
    dash.render()
    assert len(dash.log_buffer) <= dash.max_log_lines * 5


def test_headless_adapter_progress_and_dashboard():
    ui = HeadlessUIAdapter()
    prog = ui.create_progress("test", 3)
    prog.update(1)
    prog.finish()
    dash = ui.create_dashboard([], _fake_journal())
    assert isinstance(dash, NoopDashboard)
