"""Shared CSV export helpers for plugin results."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


def write_csv_rows(
    rows: Iterable[Mapping[str, Any]],
    output_path: Path,
    columns: Sequence[str],
) -> None:
    """Write rows to CSV using the provided column order."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in columns})
