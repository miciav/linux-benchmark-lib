#!/usr/bin/env python3
"""Produce a Graphviz graph of inter-component imports (lb_* packages only)."""

from __future__ import annotations

import argparse
import ast
import subprocess
from pathlib import Path
from typing import Iterable, Mapping, Set, Tuple


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a Graphviz view of how lb_* components import each other."
    )
    parser.add_argument(
        "--modules",
        nargs="+",
        default=["lb_runner", "lb_controller", "lb_ui"],
        help="Component roots to scan.",
    )
    parser.add_argument(
        "--format",
        "-T",
        default="svg",
        help="Graphviz output format.",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="component_dependencies.svg",
        help="Target file for the rendered graph.",
    )
    parser.add_argument(
        "--include-tests",
        action="store_true",
        help="Scan test folders for imports as well.",
    )
    return parser.parse_args()


def discover_py_files(module_paths: Iterable[Path], include_tests: bool) -> Iterable[Path]:
    for path in module_paths:
        if not path.exists():
            continue
        for candidate in path.rglob("*.py"):
            if candidate.name.startswith("__") and candidate.parent.name == "__pycache__":
                continue
            if not include_tests and "tests" in candidate.parts:
                continue
            yield candidate


def extract_edges(
    paths: Iterable[Path], components: Set[str]
) -> Set[Tuple[str, str]]:
    edges: Set[Tuple[str, str]] = set()
    for path in paths:
        try:
            source = path.read_text()
        except Exception:
            continue
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            continue

        owner = path.parts[0] if path.parts else None
        if owner not in components:
            # Some files can live in nested dirs (e.g. lb_runner/plugins). Derive owner by checking prefix.
            owner = next((comp for comp in components if path.match(f"{comp}/**")), owner)
        if owner not in components:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    base = alias.name.split(".")[0]
                    if base in components and base != owner:
                        edges.add((owner, base))
            elif isinstance(node, ast.ImportFrom):
                if not node.module:
                    continue
                base = node.module.split(".")[0]
                if base in components and base != owner:
                    edges.add((owner, base))
    return edges


def render_dot(
    edges: Set[Tuple[str, str]],
    components: Iterable[str],
    output: Path,
    fmt: str,
) -> None:
    dot_lines = [
        "digraph component_dependencies {",
        "  rankdir=LR;",
        "  node [shape=box, style=filled, fillcolor=\"#f5f5f5\", color=\"#555\"]",
    ]
    for comp in components:
        dot_lines.append(f'  "{comp}" [fillcolor="#d0e4ff"];')
    for src, dst in sorted(edges):
        dot_lines.append(f'  "{src}" -> "{dst}" [color="#2c7cdb"];')
    if not edges:
        dot_lines.append("  /* No inter-component imports detected */")
    dot_lines.append("}")

    dot = "\n".join(dot_lines)
    proc = subprocess.run(
        ["dot", "-T", fmt, "-o", str(output)],
        input=dot.encode(),
        check=True,
    )


def main() -> None:
    args = parse_arguments()
    modules = args.modules
    module_paths = [Path(m) for m in modules]
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    edges = extract_edges(
        discover_py_files(module_paths, include_tests=args.include_tests),
        set(modules),
    )
    render_dot(edges, modules, output_path, args.format)
    print(f"Written component graph to {output_path}")


if __name__ == "__main__":
    main()
