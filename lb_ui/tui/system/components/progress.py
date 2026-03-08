from typing import ContextManager, cast
from rich.console import Console
from lb_ui.tui.core.protocols import Progress


class RichProgress(Progress):
    def __init__(self, console: Console):
        self._console = console

    def status(self, message: str) -> ContextManager[None]:
        return cast(ContextManager[None], self._console.status(message))
