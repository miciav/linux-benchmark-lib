"""Unit tests for ResultsViewModel."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest


class TestResultsViewModel:
    """Tests for ResultsViewModel."""

    @pytest.fixture
    def mock_services(self) -> tuple[MagicMock, MagicMock]:
        """Create mock services."""
        run_catalog = MagicMock()
        config_service = MagicMock()
        return run_catalog, config_service

    @pytest.fixture
    def mock_run_info(self) -> MagicMock:
        """Create a mock RunInfo."""
        run = MagicMock()
        run.run_id = "test-run-123"
        run.output_root = Path("/output/test-run-123")
        run.report_root = Path("/reports/test-run-123")
        run.data_export_root = Path("/exports/test-run-123")
        run.journal_path = Path("/output/test-run-123/journal.yaml")
        run.hosts = ["host1", "host2"]
        run.workloads = ["stress_ng", "fio"]
        run.created_at = datetime(2024, 1, 15, 10, 30, 0)
        return run

    def test_initial_state(self, mock_services: tuple[MagicMock, MagicMock]) -> None:
        """Test initial viewmodel state."""
        from lb_gui.viewmodels.results_vm import ResultsViewModel

        run_catalog, config_service = mock_services
        vm = ResultsViewModel(run_catalog, config_service)

        assert vm.runs == []
        assert vm.selected_run is None
        assert vm.is_configured is False

    def test_configure_loads_config(
        self, mock_services: tuple[MagicMock, MagicMock]
    ) -> None:
        """Test configure() loads config and configures catalog."""
        from lb_gui.viewmodels.results_vm import ResultsViewModel

        run_catalog, config_service = mock_services
        mock_config = MagicMock()
        config_service.load_config.return_value = (mock_config, Path("/config"), None)

        vm = ResultsViewModel(run_catalog, config_service)
        result = vm.configure(Path("/config.yaml"))

        assert result is True
        assert vm.is_configured is True
        run_catalog.configure.assert_called_once_with(mock_config)

    def test_configure_handles_error(
        self, mock_services: tuple[MagicMock, MagicMock]
    ) -> None:
        """Test configure() handles errors gracefully."""
        from lb_gui.viewmodels.results_vm import ResultsViewModel

        run_catalog, config_service = mock_services
        config_service.load_config.side_effect = Exception("Config error")

        vm = ResultsViewModel(run_catalog, config_service)
        result = vm.configure()

        assert result is False
        assert vm.is_configured is False

    def test_refresh_runs_updates_list(
        self,
        mock_services: tuple[MagicMock, MagicMock],
        mock_run_info: MagicMock,
    ) -> None:
        """Test refresh_runs() updates the runs list."""
        from lb_gui.viewmodels.results_vm import ResultsViewModel

        run_catalog, config_service = mock_services
        run_catalog.list_runs.return_value = [mock_run_info]

        vm = ResultsViewModel(run_catalog, config_service)
        vm._is_configured = True
        vm.refresh_runs()

        assert len(vm.runs) == 1
        assert vm.runs[0] == mock_run_info

    def test_refresh_runs_requires_configuration(
        self, mock_services: tuple[MagicMock, MagicMock]
    ) -> None:
        """Test refresh_runs() requires configuration."""
        from lb_gui.viewmodels.results_vm import ResultsViewModel

        run_catalog, config_service = mock_services

        vm = ResultsViewModel(run_catalog, config_service)
        vm.refresh_runs()

        run_catalog.list_runs.assert_not_called()

    def test_select_run_sets_selection(
        self,
        mock_services: tuple[MagicMock, MagicMock],
        mock_run_info: MagicMock,
    ) -> None:
        """Test select_run() sets the selected run."""
        from lb_gui.viewmodels.results_vm import ResultsViewModel

        run_catalog, config_service = mock_services

        vm = ResultsViewModel(run_catalog, config_service)
        vm._runs = [mock_run_info]

        vm.select_run("test-run-123")

        assert vm.selected_run == mock_run_info

    def test_select_run_none_clears_selection(
        self,
        mock_services: tuple[MagicMock, MagicMock],
        mock_run_info: MagicMock,
    ) -> None:
        """Test select_run(None) clears selection."""
        from lb_gui.viewmodels.results_vm import ResultsViewModel

        run_catalog, config_service = mock_services

        vm = ResultsViewModel(run_catalog, config_service)
        vm._runs = [mock_run_info]
        vm._selected_run = mock_run_info

        vm.select_run(None)

        assert vm.selected_run is None

    def test_get_run_table_rows(
        self,
        mock_services: tuple[MagicMock, MagicMock],
        mock_run_info: MagicMock,
    ) -> None:
        """Test get_run_table_rows() formats runs correctly."""
        from lb_gui.viewmodels.results_vm import ResultsViewModel

        run_catalog, config_service = mock_services

        vm = ResultsViewModel(run_catalog, config_service)
        vm._runs = [mock_run_info]

        rows = vm.get_run_table_rows()

        assert len(rows) == 1
        assert rows[0][0] == "test-run-123"  # Run ID
        assert "2024-01-15" in rows[0][1]  # Created date
        assert "host1" in rows[0][2]  # Hosts
        assert "stress_ng" in rows[0][3]  # Workloads

    def test_get_run_details(
        self,
        mock_services: tuple[MagicMock, MagicMock],
        mock_run_info: MagicMock,
    ) -> None:
        """Test get_run_details() returns formatted details."""
        from lb_gui.viewmodels.results_vm import ResultsViewModel

        run_catalog, config_service = mock_services

        vm = ResultsViewModel(run_catalog, config_service)
        vm._selected_run = mock_run_info

        details = vm.get_run_details()

        assert details["Run ID"] == "test-run-123"
        assert "/output/test-run-123" in details["Output Directory"]
        assert "host1" in details["Hosts"]

    def test_open_output_directory_returns_path(
        self,
        mock_services: tuple[MagicMock, MagicMock],
        mock_run_info: MagicMock,
    ) -> None:
        """Test open_output_directory() returns correct path."""
        from lb_gui.viewmodels.results_vm import ResultsViewModel

        run_catalog, config_service = mock_services

        vm = ResultsViewModel(run_catalog, config_service)
        vm._selected_run = mock_run_info

        path = vm.open_output_directory()

        assert path == Path("/output/test-run-123")

    def test_open_output_directory_returns_none_without_selection(
        self, mock_services: tuple[MagicMock, MagicMock]
    ) -> None:
        """Test open_output_directory() returns None without selection."""
        from lb_gui.viewmodels.results_vm import ResultsViewModel

        run_catalog, config_service = mock_services

        vm = ResultsViewModel(run_catalog, config_service)

        path = vm.open_output_directory()

        assert path is None
