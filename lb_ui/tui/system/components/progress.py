from contextlib import AbstractContextManager
from typing import cast

from rich.console import Console

from lb_ui.tui.core.protocols import Progress


class RichProgress(Progress):
    def __init__(self, console: Console):
        self._console = console

    def status(self, message: str) -> AbstractContextManager[None]:
        return cast(AbstractContextManager[None], self._console.status(message))
