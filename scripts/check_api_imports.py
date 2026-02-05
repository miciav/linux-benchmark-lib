#!/usr/bin/env python3
"""Verify that cross-package imports always use the .api module.

This script enforces the architectural rule that packages should only import
from other lb_* packages through their public API surface (e.g., lb_runner.api),
never through internal modules (e.g., lb_runner.services.foo).

Usage:
    uv run python scripts/check_api_imports.py [--include-tests]
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

LB_PACKAGES = {
    "lb_common",
    "lb_plugins",
    "lb_runner",
    "lb_controller",
    "lb_app",
    "lb_ui",
    "lb_analytics",
    "lb_provisioner",
}

SKIP_DIRS = {
    "__pycache__",
    ".venv",
    "venv",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "build",
    "dist",
    ".uv_cache",
    ".git",
}


@dataclass(frozen=True)
class Violation:
    file: Path
    line: int
    importing_package: str
    target_package: str
    import_path: str

    def __str__(self) -> str:
        return (
            f"{self.file}:{self.line}: "
            f"{self.importing_package} imports {self.import_path} "
            f"(should use {self.target_package}.api)"
        )


def should_skip(path: Path) -> bool:
    return any(part in SKIP_DIRS for part in path.parts)


def discover_py_files(
    roots: Iterable[Path], include_tests: bool
) -> Iterable[tuple[Path, str]]:
    """Yield (file_path, owning_package) for all Python files."""
    for root in roots:
        if not root.exists():
            continue
        for candidate in root.rglob("*.py"):
            if should_skip(candidate):
                continue
            if not include_tests and "tests" in candidate.parts:
                continue
            yield candidate, root.name


def get_package_from_import(module: str) -> str | None:
    """Extract the lb_* package name from an import path."""
    parts = module.split(".")
    if parts and parts[0] in LB_PACKAGES:
        return parts[0]
    return None


def is_api_import(module: str) -> bool:
    """Check if the import goes through .api module."""
    parts = module.split(".")
    # Valid patterns:
    # - lb_foo (bare package import)
    # - lb_foo.api
    # - lb_foo.api.something (re-exports)
    if len(parts) == 1:
        return True  # bare import like "import lb_runner"
    if len(parts) >= 2 and parts[1] == "api":
        return True
    return False


def check_file(file_path: Path, owning_package: str) -> list[Violation]:
    """Check a single file for cross-package import violations."""
    violations: list[Violation] = []

    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
    except (SyntaxError, UnicodeDecodeError) as e:
        print(f"[WARN] Could not parse {file_path}: {e}", file=sys.stderr)
        return violations

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                target_pkg = get_package_from_import(alias.name)
                if target_pkg and target_pkg != owning_package:
                    if not is_api_import(alias.name):
                        violations.append(
                            Violation(
                                file=file_path,
                                line=node.lineno,
                                importing_package=owning_package,
                                target_package=target_pkg,
                                import_path=alias.name,
                            )
                        )
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                target_pkg = get_package_from_import(node.module)
                if target_pkg and target_pkg != owning_package:
                    if not is_api_import(node.module):
                        violations.append(
                            Violation(
                                file=file_path,
                                line=node.lineno,
                                importing_package=owning_package,
                                target_package=target_pkg,
                                import_path=node.module,
                            )
                        )

    return violations


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check that cross-package imports use .api modules."
    )
    parser.add_argument(
        "--include-tests",
        action="store_true",
        help="Include test files in the check.",
    )
    parser.add_argument(
        "--packages",
        nargs="+",
        default=sorted(LB_PACKAGES),
        help="Packages to check (default: all lb_* packages).",
    )
    args = parser.parse_args()

    roots = [Path(pkg) for pkg in args.packages]
    all_violations: list[Violation] = []

    for file_path, owning_package in discover_py_files(roots, args.include_tests):
        violations = check_file(file_path, owning_package)
        all_violations.extend(violations)

    if all_violations:
        print(f"Found {len(all_violations)} cross-package import violation(s):\n")
        # Group by importing package
        by_package: dict[str, list[Violation]] = {}
        for v in all_violations:
            by_package.setdefault(v.importing_package, []).append(v)

        for pkg in sorted(by_package.keys()):
            print(f"=== {pkg} ===")
            for v in sorted(by_package[pkg], key=lambda x: (str(x.file), x.line)):
                print(f"  {v}")
            print()

        return 1
    else:
        print("All cross-package imports correctly use .api modules.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
