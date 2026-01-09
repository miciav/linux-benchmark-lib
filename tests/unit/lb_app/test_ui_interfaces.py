"""Tests for app-level UI interfaces."""

from types import SimpleNamespace

import pytest

from lb_app.api import NoOpDashboardHandle, NoOpProgressHandle, NoOpUIAdapter


pytestmark = pytest.mark.unit_ui


def test_noop_ui_adapter_defaults() -> None:
    adapter = NoOpUIAdapter()
    adapter.show_info("info")
    adapter.show_warning("warn")
    adapter.show_error("error")
    adapter.show_success("success")
    adapter.show_panel("panel", title="title", border_style="blue")
    adapter.show_rule("rule")
    adapter.show_table("title", ["col"], [["row"]])
    with adapter.status("status"):
        pass
    progress = adapter.create_progress("desc", 1)
    assert isinstance(progress, NoOpProgressHandle)
    progress.update(1)
    progress.finish()
    journal = SimpleNamespace()
    dashboard = adapter.create_dashboard([], journal)
    assert isinstance(dashboard, NoOpDashboardHandle)
    with dashboard.live():
        dashboard.add_log("line")
        dashboard.refresh()
        dashboard.mark_event("event")
    assert adapter.prompt_multipass_scenario(["a"], "low") is None
