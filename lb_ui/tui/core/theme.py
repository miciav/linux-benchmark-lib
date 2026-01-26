from __future__ import annotations

from typing import Mapping

RICH_ACCENT = "blue"
RICH_ACCENT_BOLD = f"bold {RICH_ACCENT}"
RICH_BORDER_STYLE = RICH_ACCENT

RICH_STATUS_COLORS: dict[str, str] = {
    "failed": "red",
    "running": "yellow",
    "skipped": "dim",
    "done": "green",
    "partial": "yellow",
    "pending": "dim",
}

PRESENTER_TEMPLATES: dict[str, str] = {
    "info": "[blue]ℹ[/blue] {message}",
    "warning": "[yellow]⚠ {message}[/yellow]",
    "error": "[red]✖ {message}[/red]",
    "success": "[green]✔ {message}[/green]",
}

DASHBOARD_HOST_STYLE = "bold cyan"
DASHBOARD_ACTION_STYLE = "dim italic"
LOG_TIMING_STYLE = "dim"


def panel_title(text: str) -> str:
    return f"[{RICH_ACCENT_BOLD}]{text}[/{RICH_ACCENT_BOLD}]"


def status_text(status: str) -> str:
    color = RICH_STATUS_COLORS.get(status)
    if not color:
        return status
    return f"[{color}]{status}[/{color}]"


def presenter_message(level: str, message: str) -> str:
    template = PRESENTER_TEMPLATES.get(level, "{message}")
    return template.format(message=message)


def event_status_waiting() -> str:
    return "[dim]Event stream: waiting[/dim]"


def event_status_live(event_source: str, freshness: str) -> str:
    return f"[green]Event stream: live ({event_source}, {freshness})[/green]"


def controller_state_line(state: str) -> str:
    return f"[cyan]Controller state:[/cyan] {state}"


def warning_banner(message: str) -> str:
    return f"[bold yellow]{message}[/bold yellow]"


def prompt_toolkit_picker_style() -> Mapping[str, str]:
    return {
        "selected": "bg:#0000aa fg:white bold",
        "checked": "fg:#00ff00 bold",
        "separator": "fg:#0000aa",
        "frame.border": "fg:#0000aa",
        "frame.label": "fg:#0000aa bold",
        "search": "bg:#eeeeee fg:#000000",
        "variant-selected": "bg:#005500 fg:white bold",
        "disabled": "fg:#aa0000",
        "path": "fg:blue bold underline",
        "title": "bold",
    }
