"""Unit tests for GUIDashboardViewModel."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestGUIDashboardViewModel:
    """Tests for GUIDashboardViewModel."""

    def test_initial_state(self) -> None:
        """Test initial viewmodel state."""
        from lb_gui.viewmodels.dashboard_vm import GUIDashboardViewModel

        vm = GUIDashboardViewModel()

        assert vm.is_running is False
        assert vm.snapshot is None
        assert vm.log_lines == []
        assert vm.current_status == ""

    def test_initialize_sets_up_state(self) -> None:
        """Test initialize() sets up dashboard state."""
        from lb_gui.viewmodels.dashboard_vm import GUIDashboardViewModel

        vm = GUIDashboardViewModel()

        mock_plan = [{"name": "stress_ng", "intensity": "high"}]
        mock_journal = MagicMock()
        mock_journal.run_id = "test-run-123"
        mock_journal.tasks = {}

        with patch("lb_gui.viewmodels.dashboard_vm.build_dashboard_viewmodel") as mock_build:
            mock_app_vm = MagicMock()
            mock_snapshot = MagicMock()
            mock_snapshot.run_id = "test-run-123"
            mock_app_vm.snapshot.return_value = mock_snapshot
            mock_build.return_value = mock_app_vm

            vm.initialize(mock_plan, mock_journal)

            assert vm.is_running is True
            assert vm.snapshot == mock_snapshot
            mock_build.assert_called_once_with(mock_plan, mock_journal)

    def test_refresh_snapshot_reads_real_journal(self) -> None:
        """Test refresh_snapshot builds rows from the real journal."""
        from lb_gui.viewmodels.dashboard_vm import GUIDashboardViewModel
        from lb_controller.services.journal import RunJournal, TaskState

        vm = GUIDashboardViewModel()
        journal = RunJournal(run_id="run-1", tasks={})
        journal.add_task(TaskState(host="host1", workload="dfaas", repetition=1))

        vm.initialize([{"name": "dfaas", "intensity": "low"}], journal)
        vm.refresh_snapshot()

        rows = vm.get_journal_rows()
        assert rows
        assert rows[0][0] == "host1"

    def test_on_log_line_accumulates(self) -> None:
        """Test on_log_line accumulates log lines."""
        from lb_gui.viewmodels.dashboard_vm import GUIDashboardViewModel

        vm = GUIDashboardViewModel()
        vm._log_line_received = MagicMock()

        vm.on_log_line("Line 1")
        vm.on_log_line("Line 2")
        vm.on_log_line("Line 3")

        assert vm.log_lines == ["Line 1", "Line 2", "Line 3"]

    def test_on_status_updates_current_status(self) -> None:
        """Test on_status updates current_status."""
        from lb_gui.viewmodels.dashboard_vm import GUIDashboardViewModel

        vm = GUIDashboardViewModel()

        vm.on_status("Running benchmark")

        assert vm.current_status == "Running benchmark"

    def test_on_run_finished_updates_state(self) -> None:
        """Test on_run_finished updates running state."""
        from lb_gui.viewmodels.dashboard_vm import GUIDashboardViewModel

        vm = GUIDashboardViewModel()
        vm._is_running = True

        vm.on_run_finished(True, "")

        assert vm.is_running is False
        assert "Completed" in vm.current_status

    def test_on_run_finished_with_error(self) -> None:
        """Test on_run_finished with error updates state."""
        from lb_gui.viewmodels.dashboard_vm import GUIDashboardViewModel

        vm = GUIDashboardViewModel()
        vm._is_running = True

        vm.on_run_finished(False, "Connection failed")

        assert vm.is_running is False
        assert "Failed" in vm.current_status
        assert "Connection failed" in vm.current_status

    def test_clear_resets_state(self) -> None:
        """Test clear() resets all state."""
        from lb_gui.viewmodels.dashboard_vm import GUIDashboardViewModel

        vm = GUIDashboardViewModel()
        vm._is_running = True
        vm._log_lines = ["log1", "log2"]
        vm._current_status = "Running"
        vm._snapshot = MagicMock()

        vm.clear()

        assert vm.is_running is False
        assert vm.log_lines == []
        assert vm.current_status == ""
        assert vm.snapshot is None

    def test_get_journal_rows_empty_when_no_snapshot(self) -> None:
        """Test get_journal_rows returns empty list when no snapshot."""
        from lb_gui.viewmodels.dashboard_vm import GUIDashboardViewModel

        vm = GUIDashboardViewModel()

        rows = vm.get_journal_rows()

        assert rows == []

    def test_get_journal_rows_converts_snapshot(self) -> None:
        """Test get_journal_rows converts DashboardRows to lists."""
        from lb_gui.viewmodels.dashboard_vm import GUIDashboardViewModel
        from lb_app.api import DashboardRow

        vm = GUIDashboardViewModel()
        mock_snapshot = MagicMock()
        mock_snapshot.rows = [
            DashboardRow(
                host="host1",
                workload="stress_ng",
                intensity="high",
                status="running",
                progress="1/3",
                current_action="Running...",
                last_rep_time="10.5s",
            )
        ]
        vm._snapshot = mock_snapshot

        rows = vm.get_journal_rows()

        assert len(rows) == 1
        assert rows[0] == [
            "host1",
            "stress_ng",
            "high",
            "running",
            "1/3",
            "Running...",
            "10.5s",
        ]

    def test_get_run_id_empty_when_no_snapshot(self) -> None:
        """Test get_run_id returns empty string when no snapshot."""
        from lb_gui.viewmodels.dashboard_vm import GUIDashboardViewModel

        vm = GUIDashboardViewModel()

        run_id = vm.get_run_id()

        assert run_id == ""

    def test_get_run_id_returns_snapshot_run_id(self) -> None:
        """Test get_run_id returns run ID from snapshot."""
        from lb_gui.viewmodels.dashboard_vm import GUIDashboardViewModel

        vm = GUIDashboardViewModel()
        mock_snapshot = MagicMock()
        mock_snapshot.run_id = "test-run-456"
        vm._snapshot = mock_snapshot

        run_id = vm.get_run_id()

        assert run_id == "test-run-456"
