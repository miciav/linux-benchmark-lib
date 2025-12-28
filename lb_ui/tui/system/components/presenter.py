from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from lb_ui.tui.system.components.presenter_base import PresenterBase, PresenterSink

_LEVEL_TEMPLATES = {
    "info": "[blue]ℹ[/blue] {message}",
    "warning": "[yellow]⚠ {message}[/yellow]",
    "error": "[red]✖ {message}[/red]",
    "success": "[green]✔ {message}[/green]",
}


class _RichPresenterSink(PresenterSink):
    def __init__(self, console: Console) -> None:
        self._console = console

    def emit(self, level: str, message: str) -> None:
        template = _LEVEL_TEMPLATES.get(level, "{message}")
        self._console.print(template.format(message=message))

    def emit_panel(
        self,
        message: str,
        title: str | None,
        border_style: str | None,
    ) -> None:
        self._console.print(Panel(message, title=title, border_style=border_style))

    def emit_rule(self, title: str) -> None:
        self._console.print(Rule(title))


class RichPresenter(PresenterBase):
    def __init__(self, console: Console) -> None:
        super().__init__(_RichPresenterSink(console))
