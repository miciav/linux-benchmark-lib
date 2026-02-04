import pytest

from tests.helpers.optional_imports import module_available


def test_lb_gui_dependency_availability() -> None:
    if not module_available("PySide6") or not module_available("lb_gui.viewmodels"):
        pytest.skip("lb_gui dependencies missing")
    assert module_available("lb_gui.viewmodels") is True
