"""Formatting helpers for run output."""

from __future__ import annotations

import re


def _slug_phase_label(phase: str) -> str:
    """Normalize phase labels for consistent rendering."""
    cleaned = phase.replace(":", "-").strip()
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", cleaned)
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    return cleaned.strip("-").lower() or "run"


def format_bullet_line(
    phase: str,
    message: str,
    host_label: str | None = None,
) -> str:
    """Format a log line with a phase tag and optional host label."""
    phase_clean = _slug_phase_label(phase)
    host_prefix = f"({host_label}) " if host_label else ""
    return f"• [{phase_clean}] {host_prefix}{message}"
