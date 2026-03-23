from __future__ import annotations

from typing import Mapping

# ── Accent & borders ────────────────────────────────────────────────────────
RICH_ACCENT = "cyan"
RICH_ACCENT_BOLD = f"bold {RICH_ACCENT}"
RICH_BORDER_STYLE = "bright_black"        # subtle grey — secondary panels
RICH_BORDER_STYLE_ACTIVE = RICH_ACCENT    # cyan — primary/active panels

# ── Status colours (kept for backward compat with status_text()) ─────────────
RICH_STATUS_COLORS: dict[str, str] = {
    "failed": "red",
    "running": "yellow",
    "skipped": "dim",
    "done": "green",
    "partial": "yellow",
    "pending": "dim",
}

# ── Status badges (icon + label) ─────────────────────────────────────────────
RICH_STATUS_BADGES: dict[str, str] = {
    "failed":  "[bold red]✗ failed[/bold red]",
    "running": "[bold yellow]⟳ running[/bold yellow]",
    "skipped": "[bright_black]⊘ skipped[/bright_black]",
    "done":    "[bold green]✓ done[/bold green]",
    "partial": "[yellow]◑ partial[/yellow]",
    "pending": "[bright_black]· pending[/bright_black]",
}

# ── Presenter templates ───────────────────────────────────────────────────────
PRESENTER_TEMPLATES: dict[str, str] = {
    "info":    "[cyan]●[/cyan] {message}",
    "warning": "[bold yellow]▲ {message}[/bold yellow]",
    "error":   "[bold red]✗ {message}[/bold red]",
    "success": "[bold green]✓ {message}[/bold green]",
}

# ── Dashboard styles ──────────────────────────────────────────────────────────
DASHBOARD_HOST_STYLE = "bold white"
DASHBOARD_ACTION_STYLE = "white"        # was "dim italic" — now legible
LOG_TIMING_STYLE = "bright_black"

# ── Picker keybinding hint strings ────────────────────────────────────────────
PICKER_KEYBINDINGS_FLAT_SINGLE = (
    "↑↓:navigate  Enter:confirm  Esc:cancel  Ctrl+R:clear"
)
PICKER_KEYBINDINGS_FLAT_MULTI = (
    "↑↓:navigate  Space:toggle  →:options  Enter:confirm  Esc:cancel  Ctrl+R:clear"
)
PICKER_KEYBINDINGS_HIERARCHICAL = (
    "↑↓:navigate  Enter/→:open  ←/⌫:back  Esc:cancel"
)
PICKER_KEYBINDINGS_VARIANTS = (
    "↑↓:navigate  Enter:select  ←/⌫:back"
)


# ── Public helpers ────────────────────────────────────────────────────────────

def panel_title(text: str) -> str:
    return f"[{RICH_ACCENT_BOLD}]{text}[/{RICH_ACCENT_BOLD}]"


def status_text(status: str) -> str:
    """Return Rich-markup coloured status text (no icon). Kept for compat."""
    color = RICH_STATUS_COLORS.get(status)
    if not color:
        return status
    return f"[{color}]{status}[/{color}]"


def status_badge(status: str) -> str:
    """Return a Rich-markup badge with icon for the given status."""
    badge = RICH_STATUS_BADGES.get(status)
    if badge is None:
        return status
    return badge


def progress_bar(done: int, total: int, width: int = 8) -> str:
    """Render a Unicode block progress bar, e.g. ████░░░░ 3/5."""
    if total == 0:
        return f"[bright_black]{'─' * width}[/bright_black]"
    filled = int(width * done / total)
    bar = "█" * filled + "░" * (width - filled)
    color = "green" if done >= total else "cyan"
    return f"[{color}]{bar}[/{color}] [bright_black]{done}/{total}[/bright_black]"


def presenter_message(level: str, message: str) -> str:
    template = PRESENTER_TEMPLATES.get(level, "{message}")
    return template.format(message=message)


def event_status_waiting() -> str:
    return "[bright_black]Event stream: waiting[/bright_black]"


def event_status_live(event_source: str, freshness: str) -> str:
    live = "[cyan]● Event stream: live[/cyan]"
    meta = f"[bright_black]({event_source}, {freshness})[/bright_black]"
    return f"{live} {meta}"


def controller_state_line(state: str) -> str:
    return f"[cyan]Controller:[/cyan] {state}"


def warning_banner(message: str) -> str:
    return f"[bold yellow]▲ {message}[/bold yellow]"


def prompt_toolkit_picker_style() -> Mapping[str, str]:
    return {
        "selected":         "bg:#006080 fg:white bold",
        "checked":          "fg:#00cc88 bold",
        "separator":        "fg:#444444",
        "frame.border":     "fg:#444444",
        "frame.label":      "fg:#00aacc bold",
        "search":           "bg:#1a1a2e fg:#00ccff",
        "variant-selected": "bg:#004433 fg:#00ff88 bold",
        "disabled":         "fg:#664444",
        "path":             "fg:#00aacc bold underline",
        "title":            "bold",
        "footer":           "bg:#111111 fg:#666666",
        "footer.key":       "fg:#00aacc bold",
    }
