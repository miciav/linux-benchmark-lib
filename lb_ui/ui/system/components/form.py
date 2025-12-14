from typing import Optional
from rich.console import Console
from rich.prompt import Prompt, Confirm
from lb_ui.ui.system.protocols import Form

class RichForm(Form):
    def __init__(self, console: Console):
        self._console = console

    def ask(self, prompt: str, default: str | None = None, password: bool = False) -> str:
        # rich.Prompt.ask uses default=... but it prints it differently.
        # It's close enough.
        kwargs = {}
        if default is not None:
            kwargs["default"] = default
        if password:
            kwargs["password"] = True
        
        return Prompt.ask(prompt, console=self._console, **kwargs)

    def confirm(self, prompt: str, default: bool = True) -> bool:
        return Confirm.ask(prompt, console=self._console, default=default)
