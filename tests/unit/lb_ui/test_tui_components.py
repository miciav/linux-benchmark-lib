from __future__ import annotations

import pytest

from lb_ui.tui.core import theme
from lb_ui.tui.system.components.form import RichForm
from lb_ui.tui.system.components.presenter import RichPresenter
from lb_ui.tui.system.components.table import RichTablePresenter
from lb_ui.tui.system.models import TableModel

pytestmark = pytest.mark.unit_ui


class _FakeConsole:
    def __init__(self) -> None:
        self.renderables: list[object] = []

    def print(self, renderable: object) -> None:
        self.renderables.append(renderable)


def test_rich_presenter_panel_uses_secondary_title_markup() -> None:
    console = _FakeConsole()
    presenter = RichPresenter(console)  # type: ignore[arg-type]

    presenter.panel("Hello world", title="Deploy")

    panel = console.renderables[0]
    assert getattr(panel, "border_style") == theme.RICH_BORDER_STYLE
    assert theme.RICH_TITLE_SECONDARY in str(getattr(panel, "title"))


def test_rich_presenter_rule_uses_subtle_rule_style() -> None:
    console = _FakeConsole()
    presenter = RichPresenter(console)  # type: ignore[arg-type]

    presenter.rule("Section")

    rule = console.renderables[0]
    assert getattr(rule, "style") == theme.RICH_BORDER_STYLE
    assert getattr(rule, "characters") == "─"


def test_rich_table_presenter_uses_quieter_table_chrome() -> None:
    console = _FakeConsole()
    presenter = RichTablePresenter(console)  # type: ignore[arg-type]

    presenter.show(
        TableModel(
            title="Workloads",
            columns=["Name", "Status"],
            rows=[["fio", "done"]],
        )
    )

    table = console.renderables[0]
    assert getattr(table, "show_lines") is False
    assert getattr(table, "row_styles") == ["none", "dim"]
    title = getattr(table, "title")
    assert getattr(table, "title_style") == theme.RICH_TITLE_SECONDARY
    assert getattr(title, "plain") == "Workloads"


def test_rich_form_styles_prompt_text(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    def fake_prompt_ask(prompt: str, *, console: object, default: str, password: bool) -> str:
        captured["ask"] = prompt
        return "value"

    def fake_confirm_ask(prompt: str, *, console: object, default: bool) -> bool:
        captured["confirm"] = prompt
        return True

    monkeypatch.setattr(
        "lb_ui.tui.system.components.form.Prompt.ask",
        fake_prompt_ask,
    )
    monkeypatch.setattr(
        "lb_ui.tui.system.components.form.Confirm.ask",
        fake_confirm_ask,
    )

    form = RichForm(console=object())  # type: ignore[arg-type]
    assert form.ask("Target host", default="node-1") == "value"
    assert form.confirm("Continue?") is True
    assert theme.RICH_TITLE_SECONDARY in captured["ask"]
    assert theme.RICH_TITLE_SECONDARY in captured["confirm"]
