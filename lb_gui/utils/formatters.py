"""Formatting helpers for GUI display."""

from __future__ import annotations

from datetime import datetime, timezone


def format_duration(seconds: float | int | None) -> str:
    """Format a duration in seconds into a compact human string."""
    if seconds is None:
        return "-"
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return "-"

    if value < 0:
        return "-"
    if value < 60:
        return f"{value:.1f}s"
    if value < 3600:
        minutes = int(value // 60)
        rem = value - minutes * 60
        return f"{minutes}m {rem:.0f}s"
    hours = int(value // 3600)
    rem = value - hours * 3600
    minutes = int(rem // 60)
    return f"{hours}h {minutes}m"


def format_datetime(value: datetime | None, *, utc: bool = False) -> str:
    """Format a datetime for display."""
    if value is None:
        return "Unknown"
    if utc:
        value = value.astimezone(timezone.utc)
        return value.strftime("%Y-%m-%d %H:%M:%S UTC")
    return value.strftime("%Y-%m-%d %H:%M:%S")


def format_optional(value: object | None, fallback: str = "-") -> str:
    """Format optional values with a fallback string."""
    if value is None:
        return fallback
    return str(value)
