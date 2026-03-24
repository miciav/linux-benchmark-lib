# tests/unit/lb_gui/test_dashboard_view_timer.py
"""Test warning banner auto-hide via QTimer."""
from __future__ import annotations
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication
from lb_gui.views.dashboard_view import DashboardView
from lb_gui.viewmodels.dashboard_vm import GUIDashboardViewModel


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    return app


@pytest.mark.unit
def test_warning_timer_configured_correctly(qt_app):
    vm = GUIDashboardViewModel()
    view = DashboardView(vm)
    view._on_warning("disk almost full", 5.0)

    assert view._warning_timer is not None
    assert view._warning_timer.isSingleShot()
    remaining = view._warning_timer.remainingTime()
    assert 4000 <= remaining <= 5500  # within 1.5s tolerance for CI timing variance


@pytest.mark.unit
def test_warning_banner_visible_during_ttl(qt_app):
    vm = GUIDashboardViewModel()
    view = DashboardView(vm)
    view._on_warning("something bad", 30.0)
    assert not view._warning_label.isHidden()
