from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.unit.lb_gui.test_analytics_vm import vm  # noqa: F401

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def qt_app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_the_view_shows_experiments_and_the_summary(qt_app, vm):  # noqa: F811
    from lb_gui.views.analytics_view import AnalyticsView

    view = AnalyticsView(vm)
    assert view._experiment_table.rowCount() == 2
    vm.select_experiment(1)
    vm.prepare()
    assert view._summary_table.rowCount() == len(vm.preview.summary_rows())
    assert view._unify_btn.isEnabled()
    vm.unify()
    assert view._command_edit.text().startswith("lb runs analyze --experiment tuning")
