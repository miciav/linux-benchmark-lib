import pytest
from lb_ui.tui.system.components import dashboard_helpers

pytestmark = pytest.mark.unit_ui


def test_style_status_uses_badge() -> None:
    result = dashboard_helpers.style_status("done")
    assert "✓" in result
    assert "done" in result


def test_style_status_unknown_falls_back() -> None:
    result = dashboard_helpers.style_status("whatever")
    assert result == "whatever"


def test_render_progress_partial() -> None:
    result = dashboard_helpers.render_progress("3/5")
    assert "█" in result
    assert "3/5" in result


def test_render_progress_complete() -> None:
    result = dashboard_helpers.render_progress("5/5")
    assert "green" in result
    assert "5/5" in result


def test_render_progress_empty_string() -> None:
    result = dashboard_helpers.render_progress("")
    assert result == "—"


def test_render_progress_no_slash() -> None:
    result = dashboard_helpers.render_progress("pending")
    assert result == "pending"


def test_render_progress_malformed() -> None:
    result = dashboard_helpers.render_progress("a/b")
    assert result == "a/b"


def test_render_action_with_phase_badge_for_run() -> None:
    result = dashboard_helpers.render_action("container_run", "1.2s")
    assert "RUN" in result
    assert "container_run" in result
    assert "1.2s" in result


def test_render_action_with_phase_badge_for_collection() -> None:
    result = dashboard_helpers.render_action("collect metrics", "")
    assert "COL" in result
    assert "collect metrics" in result


def test_render_action_without_known_phase_has_no_badge() -> None:
    result = dashboard_helpers.render_action("warming cache", "")
    assert "warming cache" in result
    assert "RUN" not in result
    assert "COL" not in result


def test_render_action_empty_uses_idle_placeholder() -> None:
    result = dashboard_helpers.render_action("", "")
    assert "idle" in result
