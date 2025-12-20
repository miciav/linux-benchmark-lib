#!/usr/bin/env python3
"""Generate a dependency graph for a library component using pydeps."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Iterable, Sequence

from lb_common import configure_logging

DEFAULT_EXCLUDE = ["tests", "tests.*"]
DEFAULT_COMPONENTS = ["lb_runner", "lb_controller", "lb_ui"]


def build_cmd(
    module: str,
    *,
    only: str | None = None,
    excludes: Iterable[str] | None = None,
    max_cluster_size: int = 5,
    min_cluster_size: int = 2,
    fmt: str = "svg",
    output: str | Path = "dependencies.svg",
    extra: Sequence[str] | None = None,
) -> list[str]:
    """Assemble the pydeps command line."""
    only_name = only or module
    cmd = [
        "uv",
        "run",
        "pydeps",
        module,
        "--only",
        only_name,
        "--cluster",
        "--max-cluster-size",
        str(max_cluster_size),
        "--min-cluster-size",
        str(min_cluster_size),
        "-T",
        fmt,
        "-o",
        str(output),
    ]

    excludes = excludes or DEFAULT_EXCLUDE
    for pattern in excludes:
        cmd.extend(["--exclude", pattern])

    if extra:
        cmd.extend(extra)

    return cmd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convenience wrapper around pydeps for visualizing component dependencies."
    )
    parser.add_argument(
        "module",
        nargs="?",
        help="Top-level module/package to analyze (e.g. lb_runner). Required unless --all is set.",
    )
    parser.add_argument(
        "--only",
        help="Restrict the graph to this package (defaults to the module argument).",
    )
    parser.add_argument(
        "--max-cluster-size",
        type=int,
        default=5,
        help="Maximum number of modules grouped together in a cluster.",
    )
    parser.add_argument(
        "--min-cluster-size",
        type=int,
        default=2,
        help="Minimum number of modules required to form a cluster.",
    )
    parser.add_argument(
        "--format",
        "-T",
        default="svg",
        help="pydeps output format.",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="dependencies.svg",
        help="Output file path for the generated graph.",
    )
    parser.add_argument(
        "--out-dir",
        default="dependency_graphs",
        help="Directory to write graphs when using --all.",
    )
    parser.add_argument(
        "--exclude",
        "-x",
        action="append",
        help="Additional exclude patterns passed to pydeps.",
    )
    parser.add_argument(
        "--extra",
        "-e",
        nargs="*",
        help="Additional pydeps arguments to append unchanged.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Generate graphs for every default component instead of a single module.",
    )
    parser.add_argument(
        "--modules",
        nargs="+",
        default=DEFAULT_COMPONENTS,
        help="List of components to process when --all is set.",
    )
    return parser.parse_args()


def main() -> None:
    configure_logging()
    args = parse_args()
    if args.all:
        if args.module:
            print("Ignoring positional module argument when --all is used.")
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        targets = args.modules
        for module in targets:
            output_path = out_dir / f"{module}.{args.format}"
            cmd = build_cmd(
                module,
                only=args.only,
                excludes=args.exclude,
                max_cluster_size=args.max_cluster_size,
                min_cluster_size=args.min_cluster_size,
                fmt=args.format,
                output=output_path,
                extra=args.extra,
            )
            print("Running:", " ".join(cmd))
            subprocess.run(cmd, check=True)
    else:
        if not args.module:
            raise SystemExit("error: module argument is required unless --all is set")
        cmd = build_cmd(
            args.module,
            only=args.only,
            excludes=args.exclude,
            max_cluster_size=args.max_cluster_size,
            min_cluster_size=args.min_cluster_size,
            fmt=args.format,
            output=args.output,
            extra=args.extra,
        )
        print("Running:", " ".join(cmd))
        subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
