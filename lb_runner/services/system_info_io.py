"""Persistence helpers for system info outputs."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from lb_runner.services.system_info_types import SystemInfo


def write_outputs(
    info: SystemInfo, json_path: Path | None, csv_path: Path | None
) -> None:
    """Persist collected info to JSON/CSV if paths are provided."""
    if json_path:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(info.to_dict(), indent=2), encoding="utf-8")
    if csv_path:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["category", "name", "value"])
            writer.writeheader()
            for row in info.to_csv_rows():
                writer.writerow(row)
