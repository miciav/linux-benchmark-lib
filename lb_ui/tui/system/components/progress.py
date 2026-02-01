from typing import ContextManager
from rich.console import Console
from lb_ui.tui.core.protocols import Progress

class RichProgress(Progress):
    def __init__(self, console: Console):
        self._console = console

    def status(self, message: str) -> ContextManager[None]:
        return self._console.status(message)
