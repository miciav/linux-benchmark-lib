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
