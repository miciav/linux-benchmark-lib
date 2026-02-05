"""Ensure the runner, controller, and UI parts can be installed/imported in isolation."""

import importlib
import sys
from pathlib import Path
import tomllib

import pytest

pytestmark = pytest.mark.unit_controller


def _import_without(additional_path: str, module_name: str) -> None:
    """
    Import ``module_name`` while verifying that no modules are pulled
    from ``additional_path`` during the import (simulates independent install).
    """
    before = set(sys.modules)
    importlib.import_module(module_name)
    added = set(sys.modules) - before
    for mod in added:
        if mod == additional_path or mod.startswith(f"{additional_path}."):
            raise AssertionError(
                f"Importing {module_name} unexpectedly loaded {mod} from {additional_path}"
            )


def test_runner_package_import_does_not_drag_controller_modules(monkeypatch):
    """lb_runner should not automatically load lb_controller when imported."""
    # Ensure lb_controller is not already loaded so we can observe new imports.
    for mod in list(sys.modules):
        if mod.startswith("lb_controller"):
            del sys.modules[mod]
    _import_without("lb_controller", "lb_runner")


def test_controller_is_importable_even_without_extra_optional_packages():
    """
    The controller component should import cleanly without requiring optional extras.
    """
    from lb_controller import api  # noqa: F401
    import lb_controller  # noqa: F401

    assert hasattr(api, "BenchmarkController")
    assert not hasattr(api, "ConfigService")
    assert not hasattr(lb_controller, "BenchmarkController")


def test_pyproject_lists_component_cli_scripts():
    """The project scripts expose the runner/controller/UI entry points."""
    data = tomllib.loads(Path("pyproject.toml").read_text())
    scripts = data.get("project", {}).get("scripts", {})
    expected = {
        "lb": "lb_ui.cli.main:main",
        "lb-ui": "lb_ui.cli.main:main",
    }
    for name, target in expected.items():
        assert scripts.get(name) == target, f"{name} script missing or misconfigured"


def test_controller_extra_is_defined():
    """There should be a controller extra so the orchestration stack can be installed separately."""
    data = tomllib.loads(Path("pyproject.toml").read_text())
    extras = data.get("project", {}).get("optional-dependencies", {})
    assert "controller" in extras
    assert extras["controller"], "Controller extra should list dependencies"
