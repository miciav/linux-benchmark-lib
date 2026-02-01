"""Unit tests for AnalyticsViewModel."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest


class TestAnalyticsViewModel:
    """Tests for AnalyticsViewModel."""

    @pytest.fixture
    def mock_services(self) -> tuple[MagicMock, MagicMock]:
        """Create mock services."""
        analytics_service = MagicMock()
        analytics_service.get_available_kinds.return_value = ["aggregate"]
        run_catalog = MagicMock()
        return analytics_service, run_catalog

    @pytest.fixture
    def mock_run_info(self) -> MagicMock:
        """Create a mock RunInfo."""
        run = MagicMock()
        run.run_id = "test-run-123"
        run.output_root = Path("/output/test-run-123")
        run.hosts = ["host1", "host2"]
        run.workloads = ["stress_ng", "fio"]
        run.created_at = datetime(2024, 1, 15, 10, 30, 0)
        return run

    def test_initial_state(
        self, mock_services: tuple[MagicMock, MagicMock]
    ) -> None:
        """Test initial viewmodel state."""
        from lb_gui.viewmodels.analytics_vm import AnalyticsViewModel

        analytics, run_catalog = mock_services
        vm = AnalyticsViewModel(analytics, run_catalog)

        assert vm.runs == []
        assert vm.selected_run is None
        assert vm.selected_workloads == []
        assert vm.selected_hosts == []
        assert vm.last_artifacts == []

    def test_refresh_runs_updates_list(
        self,
        mock_services: tuple[MagicMock, MagicMock],
        mock_run_info: MagicMock,
    ) -> None:
        """Test refresh_runs() updates the runs list."""
        from lb_gui.viewmodels.analytics_vm import AnalyticsViewModel

        analytics, run_catalog = mock_services
        run_catalog.list_runs.return_value = [mock_run_info]

        vm = AnalyticsViewModel(analytics, run_catalog)
        vm.refresh_runs()

        assert len(vm.runs) == 1
        assert vm.runs[0] == mock_run_info

    def test_select_run_populates_filters(
        self,
        mock_services: tuple[MagicMock, MagicMock],
        mock_run_info: MagicMock,
    ) -> None:
        """Test select_run() populates workloads and hosts filters."""
        from lb_gui.viewmodels.analytics_vm import AnalyticsViewModel

        analytics, run_catalog = mock_services

        vm = AnalyticsViewModel(analytics, run_catalog)
        vm._runs = [mock_run_info]

        vm.select_run("test-run-123")

        assert vm.selected_run == mock_run_info
        assert vm.selected_workloads == ["stress_ng", "fio"]
        assert vm.selected_hosts == ["host1", "host2"]

    def test_select_run_none_clears_state(
        self,
        mock_services: tuple[MagicMock, MagicMock],
        mock_run_info: MagicMock,
    ) -> None:
        """Test select_run(None) clears selection state."""
        from lb_gui.viewmodels.analytics_vm import AnalyticsViewModel

        analytics, run_catalog = mock_services

        vm = AnalyticsViewModel(analytics, run_catalog)
        vm._runs = [mock_run_info]
        vm._selected_run = mock_run_info
        vm._selected_workloads = ["stress_ng"]
        vm._selected_hosts = ["host1"]

        vm.select_run(None)

        assert vm.selected_run is None
        assert vm.selected_workloads == []
        assert vm.selected_hosts == []

    def test_can_run_analytics_requires_run(
        self, mock_services: tuple[MagicMock, MagicMock]
    ) -> None:
        """Test can_run_analytics() requires selected run."""
        from lb_gui.viewmodels.analytics_vm import AnalyticsViewModel

        analytics, run_catalog = mock_services

        vm = AnalyticsViewModel(analytics, run_catalog)

        can_run, error = vm.can_run_analytics()

        assert can_run is False
        assert "No run selected" in error

    def test_can_run_analytics_requires_output_root(
        self,
        mock_services: tuple[MagicMock, MagicMock],
        mock_run_info: MagicMock,
    ) -> None:
        """Test can_run_analytics() requires output_root."""
        from lb_gui.viewmodels.analytics_vm import AnalyticsViewModel

        analytics, run_catalog = mock_services
        mock_run_info.output_root = None

        vm = AnalyticsViewModel(analytics, run_catalog)
        vm._selected_run = mock_run_info

        can_run, error = vm.can_run_analytics()

        assert can_run is False
        assert "output directory" in error.lower()

    def test_can_run_analytics_passes_with_valid_state(
        self,
        mock_services: tuple[MagicMock, MagicMock],
        mock_run_info: MagicMock,
    ) -> None:
        """Test can_run_analytics() passes with valid state."""
        from lb_gui.viewmodels.analytics_vm import AnalyticsViewModel

        analytics, run_catalog = mock_services

        vm = AnalyticsViewModel(analytics, run_catalog)
        vm._selected_run = mock_run_info

        can_run, error = vm.can_run_analytics()

        assert can_run is True
        assert error == ""

    def test_run_analytics_calls_service(
        self,
        mock_services: tuple[MagicMock, MagicMock],
        mock_run_info: MagicMock,
    ) -> None:
        """Test run_analytics() calls the analytics service."""
        from lb_gui.viewmodels.analytics_vm import AnalyticsViewModel

        analytics, run_catalog = mock_services
        expected_artifacts = [Path("/report.html")]
        analytics.run_analytics.return_value = expected_artifacts

        vm = AnalyticsViewModel(analytics, run_catalog)
        vm._selected_run = mock_run_info
        vm._selected_workloads = ["stress_ng"]
        vm._selected_hosts = ["host1"]

        vm.run_analytics()

        analytics.run_analytics.assert_called_once()
        call_kwargs = analytics.run_analytics.call_args.kwargs
        assert call_kwargs["run_info"] == mock_run_info
        assert call_kwargs["workloads"] == ["stress_ng"]
        assert call_kwargs["hosts"] == ["host1"]

    def test_run_analytics_updates_artifacts(
        self,
        mock_services: tuple[MagicMock, MagicMock],
        mock_run_info: MagicMock,
    ) -> None:
        """Test run_analytics() updates last_artifacts."""
        from lb_gui.viewmodels.analytics_vm import AnalyticsViewModel

        analytics, run_catalog = mock_services
        expected_artifacts = [Path("/report.html"), Path("/data.csv")]
        analytics.run_analytics.return_value = expected_artifacts

        vm = AnalyticsViewModel(analytics, run_catalog)
        vm._selected_run = mock_run_info

        vm.run_analytics()

        assert vm.last_artifacts == expected_artifacts

    def test_available_workloads_from_selected_run(
        self,
        mock_services: tuple[MagicMock, MagicMock],
        mock_run_info: MagicMock,
    ) -> None:
        """Test available_workloads comes from selected run."""
        from lb_gui.viewmodels.analytics_vm import AnalyticsViewModel

        analytics, run_catalog = mock_services

        vm = AnalyticsViewModel(analytics, run_catalog)
        vm._selected_run = mock_run_info

        assert vm.available_workloads == ["stress_ng", "fio"]

    def test_available_workloads_empty_without_run(
        self, mock_services: tuple[MagicMock, MagicMock]
    ) -> None:
        """Test available_workloads is empty without selected run."""
        from lb_gui.viewmodels.analytics_vm import AnalyticsViewModel

        analytics, run_catalog = mock_services

        vm = AnalyticsViewModel(analytics, run_catalog)

        assert vm.available_workloads == []

    def test_get_run_table_rows(
        self,
        mock_services: tuple[MagicMock, MagicMock],
        mock_run_info: MagicMock,
    ) -> None:
        """Test get_run_table_rows() formats runs correctly."""
        from lb_gui.viewmodels.analytics_vm import AnalyticsViewModel

        analytics, run_catalog = mock_services

        vm = AnalyticsViewModel(analytics, run_catalog)
        vm._runs = [mock_run_info]

        rows = vm.get_run_table_rows()

        assert len(rows) == 1
        assert rows[0][0] == "test-run-123"
        assert "2024-01-15" in rows[0][1]
