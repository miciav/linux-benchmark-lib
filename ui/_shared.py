from __future__ import annotations

from typing import Sequence


def format_table(title: str, columns: Sequence[str], rows: list[Sequence[str]]) -> str:
    """Build a deterministic ASCII table representation."""
    col_widths = [len(col) for col in columns]
    for row in rows:
        for idx, cell in enumerate(row):
            col_widths[idx] = max(col_widths[idx], len(str(cell)))

    def _fmt_row(items: Sequence[str]) -> str:
        return " | ".join(str(item).ljust(col_widths[idx]) for idx, item in enumerate(items))

    parts = [title, _fmt_row(columns), "-+-".join("-" * w for w in col_widths)]
    parts.extend(_fmt_row(row) for row in rows)
    return "\n".join(parts)
