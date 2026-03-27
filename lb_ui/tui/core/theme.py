from __future__ import annotations

from typing import Mapping

# ── Accent & borders ────────────────────────────────────────────────────────
RICH_ACCENT = "cyan"
RICH_ACCENT_BOLD = f"bold {RICH_ACCENT}"
RICH_BORDER_STYLE = "bright_black"        # subtle grey — secondary panels
RICH_BORDER_STYLE_ACTIVE = RICH_ACCENT    # cyan — primary/active panels
RICH_TITLE_SECONDARY = "bold white"
RICH_META_MUTED = "bright_black"
RICH_EMPTY_TEXT = "italic bright_black"

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
DASHBOARD_ACTION_STYLE = "white"
DASHBOARD_HEADER_STYLE = "bold white"
TABLE_ROW_STYLES = ["none", "dim"]
LOG_TIMING_STYLE = "bright_black"
ACTION_PHASE_STYLES: dict[str, str] = {
    "SET": "black on #7fe3d4",
    "RUN": "black on #5cc8ff",
    "COL": "black on #b8f28f",
    "END": "black on #f2c078",
}

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

def panel_title(
    text: str, meta: str | None = None, *, active: bool = True
) -> str:
    title_style = RICH_ACCENT_BOLD if active else RICH_TITLE_SECONDARY
    if not meta:
        return f"[{title_style}]{text}[/{title_style}]"
    meta_style = RICH_ACCENT if active else RICH_META_MUTED
    return (
        f"[{title_style}]{text}[/{title_style}] "
        f"[{RICH_META_MUTED}]•[/{RICH_META_MUTED}] "
        f"[{meta_style}]{meta}[/{meta_style}]"
    )


def muted(text: str) -> str:
    return f"[{RICH_META_MUTED}]{text}[/{RICH_META_MUTED}]"


def empty_state(text: str) -> str:
    return f"[{RICH_EMPTY_TEXT}]{text}[/{RICH_EMPTY_TEXT}]"


def form_prompt(text: str) -> str:
    return f"[{RICH_TITLE_SECONDARY}]{text}[/{RICH_TITLE_SECONDARY}]"


def action_phase_badge(label: str) -> str:
    style = ACTION_PHASE_STYLES.get(label)
    if not style:
        return label
    return f"[{style}] {label} [/{style}]"


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
    return f"[{RICH_TITLE_SECONDARY}]Controller[/{RICH_TITLE_SECONDARY}] {muted('•')} {state}"


def warning_banner(message: str) -> str:
    return f"[bold yellow]▲ {message}[/bold yellow]"


def prompt_toolkit_picker_style() -> Mapping[str, str]:
    return {
        "selected":         "bg:#14323a fg:#eafffb bold",
        "checked":          "fg:#67d6c3 bold",
        "separator":        "fg:#3c464d",
        "frame.border":     "fg:#3c464d",
        "frame.label":      "fg:#7fe3d4 bold",
        "search":           "bg:#171c20 fg:#dffcf7",
        "variant-selected": "bg:#163b38 fg:#effffb bold",
        "disabled":         "fg:#66727a",
        "path":             "fg:#7fe3d4 bold",
        "title":            "fg:#f4fffd bold",
        "footer":           "bg:#101316 fg:#73818a",
        "footer.key":       "fg:#7fe3d4 bold",
    }
