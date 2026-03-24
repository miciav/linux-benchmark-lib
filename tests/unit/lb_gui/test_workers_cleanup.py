"""Test that workers use the correct Qt thread cleanup pattern."""
from __future__ import annotations
import pytest

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qt_app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.mark.unit
def test_run_worker_has_no_cleanup_thread_method(qt_app):
    from lb_gui.workers.run_worker import RunWorker
    from unittest.mock import MagicMock
    worker = RunWorker(MagicMock(), MagicMock())
    assert not hasattr(worker, "_cleanup_thread"), (
        "_cleanup_thread must be removed; use thread.finished→deleteLater pattern"
    )


@pytest.mark.unit
def test_analytics_worker_has_no_cleanup_thread_method(qt_app):
    from lb_gui.workers.analytics_worker import AnalyticsWorker
    from unittest.mock import MagicMock
    worker = AnalyticsWorker(MagicMock(), MagicMock(), MagicMock())
    assert not hasattr(worker, "_cleanup_thread")


@pytest.mark.unit
def test_doctor_worker_has_no_cleanup_thread_method(qt_app):
    from lb_gui.workers.doctor_worker import DoctorWorker
    from unittest.mock import MagicMock
    worker = DoctorWorker(MagicMock(), None)
    assert not hasattr(worker, "_cleanup_thread")


@pytest.mark.unit
def test_run_worker_thread_ref_cleared_by_clear_thread(qt_app):
    """_clear_thread() (connected to thread.finished) clears the reference."""
    from lb_gui.workers.run_worker import RunWorker
    from unittest.mock import MagicMock
    from PySide6.QtCore import QThread

    worker = RunWorker(MagicMock(), MagicMock())
    worker._thread = QThread()
    assert worker.is_running()

    worker._clear_thread()

    assert worker._thread is None
    assert not worker.is_running()


@pytest.mark.unit
def test_analytics_worker_thread_ref_cleared_by_clear_thread(qt_app):
    from lb_gui.workers.analytics_worker import AnalyticsWorker
    from unittest.mock import MagicMock
    from PySide6.QtCore import QThread

    worker = AnalyticsWorker(MagicMock(), MagicMock(), MagicMock())
    worker._thread = QThread()
    assert worker.is_running()

    worker._clear_thread()

    assert worker._thread is None
    assert not worker.is_running()


@pytest.mark.unit
def test_doctor_worker_thread_ref_cleared_by_clear_thread(qt_app):
    from lb_gui.workers.doctor_worker import DoctorWorker
    from unittest.mock import MagicMock
    from PySide6.QtCore import QThread

    worker = DoctorWorker(MagicMock(), None)
    worker._thread = QThread()
    assert worker.is_running()

    worker._clear_thread()

    assert worker._thread is None
    assert not worker.is_running()
