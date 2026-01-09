"""Tests for UI adapters and dashboard behaviors (non-visual)."""

from contextlib import AbstractContextManager, contextmanager
import threading
from types import SimpleNamespace

import pytest

from lb_ui.api import RichDashboard
from lb_ui.api import HeadlessUI
from lb_ui.api import TUIAdapter, ThreadedDashboardHandle
from lb_controller.api import RunJournal
from lb_ui.tui.system.components.dashboard_adapter import DashboardAdapter


pytestmark = pytest.mark.unit_ui


def _fake_journal():
    cfg = SimpleNamespace(remote_hosts=[SimpleNamespace(name="localhost")], repetitions=1, workloads={"w": {}})
    journal = RunJournal.initialize("run-1", cfg, ["w"])
    return journal


def test_dashboard_log_slicing_respects_height():
    journal = _fake_journal()
    plan = [{"name": "w", "plugin": "stress_ng", "intensity": "low"}]
    dash = RichDashboard(
        console=SimpleNamespace(size=SimpleNamespace(height=20, width=80)),  # type: ignore[arg-type]
        plan_rows=plan,
        journal=journal,
    )
    # Simulate many logs
    for i in range(50):
        dash.add_log(f"log {i}")
    dash.render()
    assert len(dash.log_buffer) <= dash.max_log_lines * 5


def test_headless_adapter_progress_and_dashboard():
    ui = HeadlessUI()
    adapter = TUIAdapter(ui)
    prog = adapter.create_progress("test", 3)
    prog.update(1)
    prog.finish()
    dash = adapter.create_dashboard([], _fake_journal())
    assert isinstance(dash, ThreadedDashboardHandle)


def test_headless_dashboard_records_logs():
    ui = HeadlessUI()
    dashboard = ui.dashboard.create([], _fake_journal())
    with dashboard.live():
        dashboard.add_log("line-1")
    assert ui.recorded_dashboard_logs == ["line-1"]
    assert "DASHBOARD: live()" in ui.recorded_messages


def test_threaded_dashboard_dispatches_calls():
    class _RecordingDashboard:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str | None]] = []
            self.log_event = threading.Event()
            self.refresh_event = threading.Event()

        @contextmanager
        def live(self) -> AbstractContextManager[None]:
            yield

        def add_log(self, line: str) -> None:
            self.calls.append(("add_log", line))
            self.log_event.set()

        def refresh(self) -> None:
            self.calls.append(("refresh", None))
            self.refresh_event.set()

        def mark_event(self, source: str) -> None:
            self.calls.append(("mark_event", source))

        def set_warning(self, message: str, ttl: float = 10.0) -> None:
            self.calls.append(("set_warning", message))

        def clear_warning(self) -> None:
            self.calls.append(("clear_warning", None))

        def set_controller_state(self, state: str) -> None:
            self.calls.append(("set_controller_state", state))

    sink = _RecordingDashboard()
    dashboard = ThreadedDashboardHandle(sink)
    with dashboard.live():
        dashboard.add_log("log")
        assert sink.log_event.wait(1.0)
        assert sink.refresh_event.wait(1.0)
    assert ("add_log", "log") in sink.calls
    assert ("refresh", None) in sink.calls


def test_dashboard_adapter_dispatches_unthreaded_calls():
    class _RecordingDashboard:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str | None]] = []

        @contextmanager
        def live(self) -> AbstractContextManager[None]:
            yield

        def add_log(self, line: str) -> None:
            self.calls.append(("add_log", line))

        def refresh(self) -> None:
            self.calls.append(("refresh", None))

        def mark_event(self, source: str) -> None:
            self.calls.append(("mark_event", source))

        def set_warning(self, message: str, ttl: float = 10.0) -> None:
            self.calls.append(("set_warning", message))

        def clear_warning(self) -> None:
            self.calls.append(("clear_warning", None))

        def set_controller_state(self, state: str) -> None:
            self.calls.append(("set_controller_state", state))

    sink = _RecordingDashboard()
    dashboard = DashboardAdapter(sink, threaded=False)
    with dashboard.live():
        dashboard.add_log("line")
        dashboard.refresh()
        dashboard.mark_event("host-1")
        dashboard.set_warning("warning")
        dashboard.clear_warning()
        dashboard.set_controller_state("running")

    assert ("add_log", "line") in sink.calls
    assert ("refresh", None) in sink.calls
    assert ("mark_event", "host-1") in sink.calls
    assert ("set_warning", "warning") in sink.calls
    assert ("clear_warning", None) in sink.calls
    assert ("set_controller_state", "running") in sink.calls
