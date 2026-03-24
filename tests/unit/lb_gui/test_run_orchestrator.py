"""Tests for RunOrchestrator."""
from __future__ import annotations
import pytest

pytest.importorskip("PySide6")

from unittest.mock import MagicMock


@pytest.fixture(scope="module")
def qt_app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.mark.unit
def test_run_orchestrator_initializes_dashboard_and_starts_worker(qt_app):
    from lb_gui.services.run_orchestrator import RunOrchestrator
    from lb_gui.viewmodels.dashboard_vm import GUIDashboardViewModel

    mock_run_ctrl = MagicMock()
    mock_run_ctrl.get_run_plan.return_value = [{"name": "stress_ng", "intensity": "low"}]
    mock_worker = MagicMock()
    mock_worker.signals = MagicMock()
    mock_run_ctrl.create_worker.return_value = mock_worker
    from lb_app.api import RunJournal
    mock_run_ctrl.build_journal.return_value = RunJournal(run_id="r1", tasks={})

    dashboard_vm = GUIDashboardViewModel()
    orchestrator = RunOrchestrator(mock_run_ctrl, dashboard_vm)

    mock_request = MagicMock()
    mock_request.run_id = "r1"
    mock_request.config = MagicMock(remote_hosts=[])
    mock_request.tests = ["stress_ng"]
    mock_request.execution_mode = "remote"

    worker = orchestrator.start_run(mock_request)

    assert worker is mock_worker
    mock_worker.start.assert_called_once()
    assert dashboard_vm.snapshot is not None


@pytest.mark.unit
def test_run_orchestrator_raises_if_already_running(qt_app):
    from lb_gui.services.run_orchestrator import RunOrchestrator
    from lb_gui.viewmodels.dashboard_vm import GUIDashboardViewModel

    mock_run_ctrl = MagicMock()
    mock_worker = MagicMock()
    mock_worker.is_running.return_value = True
    mock_worker.signals = MagicMock()

    dashboard_vm = GUIDashboardViewModel()
    orchestrator = RunOrchestrator(mock_run_ctrl, dashboard_vm)
    orchestrator._current_worker = mock_worker  # simulate busy state

    mock_request = MagicMock()
    mock_request.run_id = "r2"

    with pytest.raises(RuntimeError, match="already in progress"):
        orchestrator.start_run(mock_request)
