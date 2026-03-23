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


def test_dashboard_journal_uses_placeholder_for_empty_action() -> None:
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
    assert "\u2014" in rendered  # —
