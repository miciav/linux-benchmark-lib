"""Aggregation helpers for the dashboard UI."""

from __future__ import annotations

from lb_ui.tui.core import theme


def style_status(status: str) -> str:
    return theme.status_badge(status)


def render_progress(progress_str: str) -> str:
    if not progress_str:
        return "—"
    if "/" not in progress_str:
        return progress_str
    try:
        done_s, total_s = progress_str.split("/", 1)
        done = int(done_s.strip())
        total = int(total_s.strip())
        return theme.progress_bar(done, total)
    except (ValueError, AttributeError):
        return progress_str


def computed_journal_height(row_count: int, term_height: int) -> int:
    """Pick a journal height that leaves room for logs."""
    min_height = min(30, max(10, row_count + 5))
    log_min = 6
    available = max(10, term_height - log_min)
    return min(available, min_height)


def split_timing(line: str) -> tuple[str, str]:
    text = line.strip()
    if " done in " not in text:
        return line, ""
    message, timing = text.rsplit(" done in ", 1)
    if not timing.endswith("s"):
        return line, ""
    return message.rstrip(), timing
