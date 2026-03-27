import pytest
from typing import Any
from unittest.mock import MagicMock
from io import StringIO
from rich.console import Console
from lb_ui.tui.system.components.dashboard import RichDashboard

pytestmark = pytest.mark.unit_ui


def _make_dashboard() -> RichDashboard:
    console = Console(force_terminal=True, width=120)
    viewmodel = MagicMock()
    viewmodel.snapshot.return_value = MagicMock(
        run_id="test-run",
        row_count=1,
        rows=[],
        log_metadata=MagicMock(title="Logs"),
    )
    return RichDashboard(console, viewmodel)


def test_dashboard_initial_controller_state_is_not_init() -> None:
    dash = _make_dashboard()
    assert dash.controller_state != "init"
    assert dash.controller_state == "starting\u2026"


def _render_journal_to_str(dash: RichDashboard, snapshot: Any) -> str:
    cap_console = Console(file=StringIO(), force_terminal=True, width=160)
    panel = dash._render_journal(snapshot)
    cap_console.print(panel)
    return cap_console.file.getvalue()  # type: ignore[union-attr]


def _render_status_to_str(dash: RichDashboard) -> str:
    cap_console = Console(file=StringIO(), force_terminal=True, width=120)
    snapshot = dash.viewmodel.snapshot.return_value
    panel = dash._render_status(snapshot)
    cap_console.print(panel)
    return cap_console.file.getvalue()  # type: ignore[union-attr]


def _render_logs_to_str(dash: RichDashboard, snapshot: Any) -> str:
    cap_console = Console(file=StringIO(), force_terminal=True, width=120)
    panel = dash._render_logs(snapshot)
    cap_console.print(panel)
    return cap_console.file.getvalue()  # type: ignore[union-attr]


def test_dashboard_journal_renders_progress_bar_for_fractional_progress() -> None:
    console = Console(force_terminal=True, width=120)
    viewmodel = MagicMock()
    row = MagicMock()
    row.host = "host1"
    row.workload = "stress_ng"
    row.intensity = "medium"
    row.status = "running"
    row.progress = "3/5"
    row.current_action = "step"
    row.last_rep_time = "1.2s"
    snapshot = MagicMock(
        run_id="r1", row_count=1, rows=[row], log_metadata=MagicMock(title="Logs")
    )
    dash = RichDashboard(console, viewmodel)
    rendered = _render_journal_to_str(dash, snapshot)
    assert "\u2588" in rendered  # █


def test_dashboard_journal_uses_idle_placeholder_for_empty_action() -> None:
    console = Console(force_terminal=True, width=120)
    viewmodel = MagicMock()
    row = MagicMock()
    row.host = "host1"
    row.workload = "stress_ng"
    row.intensity = "low"
    row.status = "pending"
    row.progress = "0/3"
    row.current_action = ""
    row.last_rep_time = ""
    snapshot = MagicMock(
        run_id="r1", row_count=1, rows=[row], log_metadata=MagicMock(title="Logs")
    )
    dash = RichDashboard(console, viewmodel)
    rendered = _render_journal_to_str(dash, snapshot)
    assert "idle" in rendered


def test_dashboard_status_renders_empty_warning_copy() -> None:
    dash = _make_dashboard()
    rendered = _render_status_to_str(dash)
    assert "No active warnings" in rendered


def test_dashboard_status_uses_compact_header_on_wide_layout() -> None:
    dash = _make_dashboard()
    dash.set_controller_state("running")
    dash.mark_event("tcp")
    dash.last_event_ts = 9.0
    snapshot = dash.viewmodel.snapshot.return_value

    lines = dash._status_lines(snapshot, now=10.2, available_width=120)

    assert "run test-run" in lines[0]
    assert "controller running" in lines[0]
    assert "stream live" in lines[0]
    assert "1.2s ago" in lines[0]
    assert lines[1] == dash._empty_status_message()


def test_dashboard_status_falls_back_to_multiline_on_narrow_layout() -> None:
    console = Console(force_terminal=True, width=70)
    viewmodel = MagicMock()
    viewmodel.snapshot.return_value = MagicMock(
        run_id="test-run",
        row_count=1,
        rows=[],
        log_metadata=MagicMock(title="Logs"),
    )
    dash = RichDashboard(console, viewmodel)
    dash.set_controller_state("running")
    dash.mark_event("tcp")
    dash.last_event_ts = 9.0
    snapshot = dash.viewmodel.snapshot.return_value

    lines = dash._status_lines(snapshot, now=10.2, available_width=70)

    assert lines[0].startswith("run test-run")
    assert lines[1].startswith("controller running")
    assert lines[2].startswith("stream live")
    assert "1.2s ago" in lines[2]


def test_dashboard_logs_render_empty_state_copy() -> None:
    dash = _make_dashboard()
    snapshot = dash.viewmodel.snapshot.return_value
    rendered = _render_logs_to_str(dash, snapshot)
    assert "No live activity yet" in rendered


def test_dashboard_logs_default_to_summary_mode() -> None:
    dash = _make_dashboard()
    dash.add_log("• [poll] Poll LB_EVENT stream done in 0.5s")
    dash.add_log("• [poll] Delay done in 1.0s")
    snapshot = dash.viewmodel.snapshot.return_value

    rendered = _render_logs_to_str(dash, snapshot)

    assert "mode: summary" in rendered
    assert "Polling loop" in rendered
    assert "Poll LB_EVENT stream" not in rendered


def test_dashboard_logs_toggle_to_all_mode_shows_raw_lines() -> None:
    dash = _make_dashboard()
    dash.add_log("• [poll] Poll LB_EVENT stream done in 0.5s")
    dash.add_log("• [poll] Delay done in 1.0s")
    dash._toggle_log_mode()
    snapshot = dash.viewmodel.snapshot.return_value

    rendered = _render_logs_to_str(dash, snapshot)

    assert "mode: all" in rendered
    assert "Poll LB_EVENT stream" in rendered


def test_dashboard_logs_summary_compresses_run_status_updates() -> None:
    dash = _make_dashboard()
    dash.add_log("• [run fio] (host1) 1/3 running")
    dash.add_log("• [run fio] (host1) 2/3 running")
    snapshot = dash.viewmodel.snapshot.return_value

    rendered = _render_logs_to_str(dash, snapshot)

    assert "2/3 running" in rendered
    assert "1/3 running" not in rendered

    dash._toggle_log_mode()
    rendered_all = _render_logs_to_str(dash, snapshot)
    assert "1/3 running" in rendered_all
    assert "2/3 running" in rendered_all
