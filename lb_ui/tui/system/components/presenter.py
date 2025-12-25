from typing import Optional
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from lb_ui.tui.system.protocols import Presenter

class RichPresenter(Presenter):
    def __init__(self, console: Console):
        self._console = console

    def info(self, message: str) -> None:
        self._console.print(f"[blue]ℹ[/blue] {message}")

    def warning(self, message: str) -> None:
        self._console.print(f"[yellow]⚠ {message}[/yellow]")

    def error(self, message: str) -> None:
        self._console.print(f"[red]✖ {message}[/red]")

    def success(self, message: str) -> None:
        self._console.print(f"[green]✔ {message}[/green]")

    def panel(self, message: str, title: str | None = None, border_style: str | None = None) -> None:
        self._console.print(Panel(message, title=title, border_style=border_style))

    def rule(self, title: str) -> None:
        self._console.print(Rule(title))
