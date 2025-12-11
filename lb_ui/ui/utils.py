"""UI utility helpers."""

from __future__ import annotations

from typing import Sequence


def format_table(title: str, columns: Sequence[str], rows: list[Sequence[str]]) -> str:
    """Return a simple text table for headless output."""
    # Compute column widths
    col_widths = [len(col) for col in columns]
    for row in rows:
        for idx, cell in enumerate(row):
            col_widths[idx] = max(col_widths[idx], len(str(cell)))

    def _fmt_row(values: Sequence[str]) -> str:
        parts = []
        for idx, cell in enumerate(values):
            parts.append(str(cell).ljust(col_widths[idx]))
        return " | ".join(parts)

    header = _fmt_row(columns)
    separator = "-+-".join("-" * w for w in col_widths)
    body = "\n".join(_fmt_row([str(c) for c in row]) for row in rows)
    title_line = f"== {title} ==" if title else ""
    sections = [title_line, header, separator, body] if body else [title_line, header]
    return "\n".join(s for s in sections if s)
