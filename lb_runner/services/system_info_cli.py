"""Command-line entrypoint for system information collection."""

from __future__ import annotations

import argparse
from pathlib import Path

from lb_runner.services.system_info_service import SystemInfoCollector
from lb_runner.services.system_info_io import write_outputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect system information into JSON/CSV.")
    parser.add_argument("--json", type=Path, help="Path to write JSON output")
    parser.add_argument("--csv", type=Path, help="Path to write CSV output (flattened)")
    args = parser.parse_args(argv)

    info = SystemInfoCollector().collect()
    write_outputs(info, args.json, args.csv)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
