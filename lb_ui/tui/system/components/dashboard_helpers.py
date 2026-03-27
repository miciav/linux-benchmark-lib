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


def _action_phase_label(action: str) -> str | None:
    normalized = action.strip().lower().replace("_", " ")
    if not normalized:
        return None
    if any(token in normalized for token in ("setup", "install", "bootstrap", "prepare", "provision", "init")):
        return "SET"
    if any(token in normalized for token in ("collect", "metric", "parse", "export")):
        return "COL"
    if any(token in normalized for token in ("teardown", "cleanup", "final", "stop", "close")):
        return "END"
    if any(token in normalized for token in ("run", "exec", "benchmark", "stress", "fio", "workload")):
        return "RUN"
    return None


def render_action(action: str, last_rep_time: str) -> str:
    if not action:
        return theme.empty_state("idle")

    parts: list[str] = []
    phase = _action_phase_label(action)
    if phase:
        parts.append(theme.action_phase_badge(phase))
    parts.append(action)
    if last_rep_time:
        parts.append(theme.muted(f"• {last_rep_time}"))
    return " ".join(parts)


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
