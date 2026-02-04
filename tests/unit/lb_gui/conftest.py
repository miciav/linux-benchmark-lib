"""Pytest configuration for lb_gui tests."""

from pathlib import Path

from tests.helpers.optional_imports import module_available

HAS_PYSIDE6 = module_available("PySide6")
HAS_LB_GUI = module_available("lb_gui.viewmodels")

# Skip collection of test files if GUI deps or submodule are missing.
if not HAS_PYSIDE6 or not HAS_LB_GUI:
    collect_ignore = [
        path.name
        for path in Path(__file__).parent.glob("test_*.py")
        if path.name != "test_dependencies.py"
    ]
