import pytest

import lb_ui.tui as tui

pytestmark = pytest.mark.unit_ui


def test_tui_public_api_exports() -> None:
    assert hasattr(tui, "UI")
    assert hasattr(tui, "TUI")
    assert hasattr(tui, "HeadlessUI")
    assert hasattr(tui, "Picker")
    assert hasattr(tui, "TablePresenter")
    assert hasattr(tui, "Presenter")
    assert hasattr(tui, "Form")
    assert hasattr(tui, "Progress")
