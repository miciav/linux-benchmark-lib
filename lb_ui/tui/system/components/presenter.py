from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from lb_ui.tui.core.bases import Presenter
from lb_ui.tui.core.protocols import PresenterSink
from lb_ui.tui.core import theme


class _RichPresenterSink(PresenterSink):
    def __init__(self, console: Console) -> None:
        self._console = console

    def emit(self, level: str, message: str) -> None:
        self._console.print(theme.presenter_message(level, message))

    def emit_panel(
        self,
        message: str,
        title: str | None,
        border_style: str | None,
    ) -> None:
        self._console.print(Panel(message, title=title, border_style=border_style))

    def emit_rule(self, title: str) -> None:
        self._console.print(Rule(title))


class RichPresenter(Presenter):
    def __init__(self, console: Console) -> None:
        super().__init__(_RichPresenterSink(console))
