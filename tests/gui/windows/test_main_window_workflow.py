"""Tests for MainWindow workflow logic (navigation locking, shutdown)."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from lb_gui.windows.main_window import MainWindow

# Ensure QApplication exists
qapp = QApplication.instance()
if not qapp:
    qapp = QApplication(sys.argv)


@pytest.fixture
def mock_services():
    """Mock ServiceContainer and its dependencies."""
    services = MagicMock()

    # Mock specific services used in MainWindow init
    services.plugin_service = MagicMock()
    services.config_service = MagicMock()
    services.run_catalog = MagicMock()
    services.analytics_service = MagicMock()
    services.doctor_service = MagicMock()
    services.run_controller = MagicMock()

    # Mock config service behavior to avoid NoneType errors during setup
    services.config_service.get_current_config.return_value = (None, None)

    return services


# ...


class MockView(QWidget):
    """Mock View that is a real QWidget and has signals."""

    start_run_requested = Signal(object)

    def __init__(self, *args, **kwargs):
        super().__init__()


@pytest.fixture
def main_window(mock_services):
    """Create a MainWindow instance with mocked services."""
    # Patch ViewModels and Views at their source
    # Views must return a real QWidget for QStackedWidget to accept them
    with (
        patch("lb_gui.viewmodels.RunSetupViewModel"),
        patch("lb_gui.viewmodels.GUIDashboardViewModel"),
        patch("lb_gui.viewmodels.ResultsViewModel"),
        patch("lb_gui.viewmodels.AnalyticsViewModel"),
        patch("lb_gui.viewmodels.ConfigViewModel"),
        patch("lb_gui.viewmodels.PluginsViewModel"),
        patch("lb_gui.viewmodels.DoctorViewModel"),
        patch("lb_gui.views.RunSetupView", new=MockView),
        patch("lb_gui.views.run_setup_view.RunSetupView", new=MockView),
        patch("lb_gui.views.DashboardView", side_effect=MockView),
        patch("lb_gui.views.ResultsView", side_effect=MockView),
        patch("lb_gui.views.AnalyticsView", side_effect=MockView),
        patch("lb_gui.views.ConfigView", side_effect=MockView),
        patch("lb_gui.views.PluginsView", side_effect=MockView),
        patch("lb_gui.views.DoctorView", side_effect=MockView),
    ):

        window = MainWindow(mock_services)
        yield window
        window._current_worker = None
        window.close()


def test_set_ui_busy(main_window):
    """Test that _set_ui_busy updates sidebar and cursor."""
    # Initial state
    assert main_window._sidebar.isEnabled()

    # Set busy
    main_window._set_ui_busy(True)
    assert not main_window._sidebar.isEnabled()

    # Unset busy
    main_window._set_ui_busy(False)
    assert main_window._sidebar.isEnabled()


def test_on_run_finished_success(main_window):
    """Test _on_run_finished handling for success."""
    # Simulate busy state
    main_window._set_ui_busy(True)
    main_window._current_worker = MagicMock()

    # Call handler
    main_window._on_run_finished(True, "")

    # Verify state restored
    assert main_window._sidebar.isEnabled()
    assert main_window._current_worker is None


def test_on_run_finished_failure(main_window):
    """Test _on_run_finished handling for failure."""
    # Simulate busy state
    main_window._set_ui_busy(True)
    main_window._current_worker = MagicMock()

    # Mock QMessageBox to check for critical error
    with patch.object(QMessageBox, "critical") as mock_critical:
        main_window._on_run_finished(False, "Some error")

        mock_critical.assert_called_once()
        args = mock_critical.call_args[0]
        assert "Run Failed" in args[1]  # title
        assert "Some error" in args[2]  # text

    # Verify state restored regardless of error
    assert main_window._sidebar.isEnabled()
    assert main_window._current_worker is None


def test_close_event_no_worker(main_window):
    """Test closing window with no worker running."""
    event = MagicMock()
    main_window.closeEvent(event)
    event.accept.assert_called_once()


def test_close_event_worker_running_cancel(main_window):
    """Test closing window with running worker (user cancels close)."""
    worker = MagicMock()
    worker.is_running.return_value = True
    main_window._current_worker = worker

    event = MagicMock()

    # Simulate user clicking "No" (don't force quit)
    with patch.object(
        QMessageBox, "question", return_value=QMessageBox.StandardButton.No
    ):
        main_window.closeEvent(event)
        event.ignore.assert_called_once()


def test_close_event_worker_running_confirm(main_window):
    """Test closing window with running worker (user confirms close)."""
    worker = MagicMock()
    worker.is_running.return_value = True
    main_window._current_worker = worker

    event = MagicMock()

    # Simulate user clicking "Yes" (force quit)
    with patch.object(
        QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
    ):
        main_window.closeEvent(event)
        event.accept.assert_called_once()


def test_fixture_teardown_does_not_prompt(monkeypatch, main_window):
    """Ensure fixture teardown does not trigger a confirmation dialog."""

    def fail_on_prompt(*_args, **_kwargs):
        raise AssertionError("Unexpected confirmation dialog on teardown")

    monkeypatch.setattr(QMessageBox, "question", fail_on_prompt)

    worker = MagicMock()
    worker.is_running.return_value = True
    main_window._current_worker = worker


def test_on_start_run_sets_ui_adapter_and_stop_file(main_window, mock_services):
    """Test that on_start_run injects UI adapter and tracks stop file."""
    request = MagicMock()
    request.config = MagicMock()
    request.tests = ["dfaas"]
    request.execution_mode = "remote"
    request.run_id = "run-1"
    request.stop_file = Path("/tmp/stop")
    request.ui_adapter = None

    mock_services.run_controller.get_run_plan.return_value = []
    mock_services.run_controller.build_journal.return_value = MagicMock()

    worker = MagicMock()
    worker.is_running.return_value = True
    worker.signals = MagicMock()
    for name in ("log_line", "status_line", "warning", "journal_update", "finished"):
        setattr(worker.signals, name, MagicMock())
    mock_services.run_controller.create_worker.return_value = worker

    run_setup_view = main_window.get_view("run_setup")
    run_setup_view.start_run_requested.emit(request)

    assert request.ui_adapter is not None
    assert main_window._current_stop_file == request.stop_file
    assert main_window._stop_button.isEnabled()


def test_stop_button_touches_stop_file(main_window, tmp_path):
    """Test stop button creates stop file after confirmation."""
    main_window._current_stop_file = tmp_path / "STOP"
    main_window._current_worker = MagicMock()
    main_window._current_worker.is_running.return_value = True
    main_window._set_ui_busy(True)

    with patch.object(
        QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
    ):
        main_window._on_stop_clicked()

    assert main_window._current_stop_file.exists()
