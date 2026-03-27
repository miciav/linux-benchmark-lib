from rich.console import Console
from rich.prompt import Prompt, Confirm
from lb_ui.tui.core.protocols import Form
from lb_ui.tui.core import theme


class RichForm(Form):
    def __init__(self, console: Console):
        self._console = console

    def ask(
        self, prompt: str, default: str | None = None, password: bool = False
    ) -> str:
        styled_prompt = theme.form_prompt(prompt)
        if default is not None:
            return str(
                Prompt.ask(
                    styled_prompt,
                    console=self._console,
                    default=default,
                    password=password,
                )
            )
        return str(Prompt.ask(styled_prompt, console=self._console, password=password))

    def confirm(self, prompt: str, default: bool = True) -> bool:
        return Confirm.ask(
            theme.form_prompt(prompt),
            console=self._console,
            default=default,
        )
