from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Packages with public API modules; cross-package imports should go through .api
BOUNDARIES = {
    "lb_app": "lb_app/api.py",
    "lb_controller": "lb_controller/api.py",
    "lb_runner": "lb_runner/api.py",
    "lb_plugins": "lb_plugins/api.py",
}

SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "third-party",
    "tests",  # allow tests to poke internal modules
}

FROM_RE = re.compile(r"from\s+(lb_app|lb_controller|lb_runner|lb_plugins)\.(\w+)")
IMPORT_RE = re.compile(r"import\s+(lb_app|lb_controller|lb_runner|lb_plugins)\.(\w+)")


def iter_py_files():
    for path in REPO_ROOT.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def test_cross_package_imports_use_public_api():
    violations: list[str] = []
    for path in iter_py_files():
        pkg_root = path.parts[0] if len(path.parts) > 0 else ""
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in FROM_RE.finditer(text):
            pkg, sub = match.groups()
            if pkg_root == pkg:
                continue  # internal import is allowed
            if sub != "api":
                violations.append(f"{path}: use {pkg}.api instead of {pkg}.{sub}")
        for match in IMPORT_RE.finditer(text):
            pkg, sub = match.groups()
            if pkg_root == pkg:
                continue
            if sub != "api":
                violations.append(f"{path}: use {pkg}.api instead of {pkg}.{sub}")
    if violations:
        msg = "Cross-package imports must go through public API modules:\n" + "\n".join(sorted(violations))
        pytest.fail(msg)
