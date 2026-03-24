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
def test_run_worker_thread_ref_cleared_after_run(qt_app):
    """self._thread is None and is_running() is False after _run completes."""
    from lb_gui.workers.run_worker import RunWorker
    from unittest.mock import MagicMock
    from PySide6.QtCore import QThread

    mock_client = MagicMock()
    mock_client.start_run.return_value = MagicMock()
    worker = RunWorker(mock_client, MagicMock())

    # Simulate _run directly (no real thread needed for unit test)
    worker._thread = QThread()  # set a fake thread so _run can clear it
    worker._run()

    assert worker._thread is None
    assert not worker.is_running()


@pytest.mark.unit
def test_analytics_worker_thread_ref_cleared_after_run(qt_app):
    from lb_gui.workers.analytics_worker import AnalyticsWorker
    from unittest.mock import MagicMock
    from PySide6.QtCore import QThread

    mock_service = MagicMock()
    mock_service.run_analytics.return_value = []
    worker = AnalyticsWorker(mock_service, MagicMock(), MagicMock())
    worker._thread = QThread()
    worker._run()

    assert worker._thread is None
    assert not worker.is_running()


@pytest.mark.unit
def test_doctor_worker_thread_ref_cleared_after_run(qt_app):
    from lb_gui.workers.doctor_worker import DoctorWorker
    from unittest.mock import MagicMock
    from PySide6.QtCore import QThread

    mock_service = MagicMock()
    mock_service.check_controller.return_value = MagicMock()
    mock_service.check_local_tools.return_value = MagicMock()
    worker = DoctorWorker(mock_service, None)
    worker._thread = QThread()
    worker._run()

    assert worker._thread is None
    assert not worker.is_running()
