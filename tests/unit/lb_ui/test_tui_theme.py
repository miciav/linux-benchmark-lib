import pytest

from lb_ui.tui.core import theme

pytestmark = pytest.mark.unit_ui


def test_theme_prompt_toolkit_style_has_keys() -> None:
    styles = theme.prompt_toolkit_picker_style()
    for key in (
        "selected",
        "checked",
        "separator",
        "frame.border",
        "frame.label",
        "search",
        "variant-selected",
        "disabled",
        "path",
        "title",
    ):
        assert key in styles


def test_theme_status_text_formats_known_status() -> None:
    assert theme.status_text("failed") == "[red]failed[/red]"
    assert theme.status_text("unknown") == "unknown"


def test_theme_panel_title_wraps_accent() -> None:
    title = theme.panel_title("Hello")
    assert theme.RICH_ACCENT_BOLD in title


def test_theme_accent_is_cyan() -> None:
    assert theme.RICH_ACCENT == "cyan"


def test_theme_border_hierarchy_is_distinct() -> None:
    assert theme.RICH_BORDER_STYLE_ACTIVE != theme.RICH_BORDER_STYLE


def test_theme_status_badge_known_statuses() -> None:
    for status in ("failed", "running", "skipped", "done", "partial", "pending"):
        badge = theme.status_badge(status)
        assert status in badge


def test_theme_status_badge_unknown_returns_raw() -> None:
    assert theme.status_badge("mystery") == "mystery"


def test_theme_progress_bar_partial() -> None:
    bar = theme.progress_bar(3, 5)
    assert "█" in bar
    assert "░" in bar
    assert "3/5" in bar


def test_theme_progress_bar_complete_is_green() -> None:
    bar = theme.progress_bar(5, 5)
    assert "green" in bar
    assert "░" not in bar


def test_theme_progress_bar_zero_total() -> None:
    bar = theme.progress_bar(0, 0)
    assert "─" in bar


def test_theme_picker_style_has_footer_keys() -> None:
    styles = theme.prompt_toolkit_picker_style()
    assert "footer" in styles
    assert "footer.key" in styles
