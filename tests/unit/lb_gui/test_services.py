"""Unit tests for lb_gui service layer."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestAppClientService:
    """Tests for AppClientService."""

    def test_load_config_delegates_to_client(self) -> None:
        """Test that load_config delegates to ApplicationClient."""
        from lb_gui.services.app_client import AppClientService

        service = AppClientService()
        mock_config = MagicMock()
        service._client.load_config = MagicMock(return_value=mock_config)

        result = service.load_config(Path("/test/config.yaml"))

        service._client.load_config.assert_called_once_with(Path("/test/config.yaml"))
        assert result == mock_config

    def test_get_run_plan_delegates_to_client(self) -> None:
        """Test that get_run_plan delegates to ApplicationClient."""
        from lb_gui.services.app_client import AppClientService

        service = AppClientService()
        mock_config = MagicMock()
        expected_plan = {"hosts": ["host1"], "workloads": ["stress_ng"]}
        service._client.get_run_plan = MagicMock(return_value=expected_plan)

        result = service.get_run_plan(mock_config, ["stress_ng"], "docker")

        service._client.get_run_plan.assert_called_once_with(
            mock_config, ["stress_ng"], "docker"
        )
        assert result == expected_plan


class TestGUIConfigService:
    """Tests for GUIConfigService."""

    def test_load_config_returns_tuple(self) -> None:
        """Test that load_config returns (config, path, saved_path)."""
        from lb_gui.services.config_service import GUIConfigService

        service = GUIConfigService()
        mock_config = MagicMock()
        mock_result = (mock_config, Path("/resolved"), Path("/saved"))
        service._service.load_for_read = MagicMock(return_value=mock_result)

        result = service.load_config(Path("/test/config.yaml"))

        assert result == mock_result
        service._service.load_for_read.assert_called_once()

    def test_set_plugin_enabled_delegates(self) -> None:
        """Test that set_plugin_enabled delegates correctly."""
        from lb_gui.services.config_service import GUIConfigService

        service = GUIConfigService()
        mock_platform = MagicMock()
        service._service.set_plugin_enabled = MagicMock(
            return_value=(mock_platform, Path("/platform.yaml"))
        )

        result = service.set_plugin_enabled("stress_ng", True)

        service._service.set_plugin_enabled.assert_called_once_with("stress_ng", True)
        assert result[0] == mock_platform


class TestPluginService:
    """Tests for PluginService."""

    @patch("lb_gui.services.plugin_service.reset_registry_cache")
    @patch("lb_gui.services.plugin_service.create_registry")
    def test_get_registry_creates_registry(
        self, mock_create: MagicMock, mock_reset: MagicMock
    ) -> None:
        """Test that get_registry creates and caches registry."""
        from lb_gui.services.plugin_service import PluginService

        mock_registry = MagicMock()
        mock_create.return_value = mock_registry

        service = PluginService()
        result = service.get_registry()

        mock_reset.assert_called_once()
        mock_create.assert_called_once_with(refresh=True)
        assert result == mock_registry

    @patch("lb_gui.services.plugin_service.reset_registry_cache")
    @patch("lb_gui.services.plugin_service.create_registry")
    def test_get_registry_caches_result(
        self, mock_create: MagicMock, mock_reset: MagicMock
    ) -> None:
        """Test that registry is cached on subsequent calls."""
        from lb_gui.services.plugin_service import PluginService

        mock_registry = MagicMock()
        mock_create.return_value = mock_registry

        service = PluginService()
        service.get_registry()
        service.get_registry()  # Second call should use cache

        # Only called once for initial creation
        assert mock_create.call_count == 1

    @patch("lb_gui.services.plugin_service.reset_registry_cache")
    @patch("lb_gui.services.plugin_service.create_registry")
    def test_refresh_clears_cache(
        self, mock_create: MagicMock, mock_reset: MagicMock
    ) -> None:
        """Test that refresh() clears and rebuilds cache."""
        from lb_gui.services.plugin_service import PluginService

        mock_registry = MagicMock()
        mock_create.return_value = mock_registry

        service = PluginService()
        service.get_registry()
        service.refresh()

        # Should be called twice: initial + refresh
        assert mock_create.call_count == 2

    @patch("lb_gui.services.plugin_service.reset_registry_cache")
    @patch("lb_gui.services.plugin_service.create_registry")
    @patch("lb_gui.services.plugin_service.build_plugin_table")
    def test_get_plugin_table(
        self,
        mock_build_table: MagicMock,
        mock_create: MagicMock,
        mock_reset: MagicMock,
    ) -> None:
        """Test get_plugin_table returns headers and rows."""
        from lb_gui.services.plugin_service import PluginService

        mock_registry = MagicMock()
        mock_registry.available.return_value = {"stress_ng": MagicMock()}
        mock_create.return_value = mock_registry

        mock_platform = MagicMock()
        mock_platform.is_plugin_enabled.return_value = True

        expected_headers = ["Name", "Enabled"]
        expected_rows = [["stress_ng", "Yes"]]
        mock_build_table.return_value = (expected_headers, expected_rows)

        service = PluginService()
        headers, rows = service.get_plugin_table(mock_platform)

        assert headers == expected_headers
        assert rows == expected_rows


class TestRunCatalogServiceWrapper:
    """Tests for RunCatalogServiceWrapper."""

    def test_list_runs_requires_configuration(self) -> None:
        """Test that list_runs raises if not configured."""
        from lb_gui.services.run_catalog import RunCatalogServiceWrapper

        service = RunCatalogServiceWrapper()

        with pytest.raises(RuntimeError, match="not configured"):
            service.list_runs()

    def test_configure_sets_up_service(self) -> None:
        """Test that configure() creates the underlying service."""
        from lb_gui.services.run_catalog import RunCatalogServiceWrapper

        service = RunCatalogServiceWrapper()
        mock_config = MagicMock()

        service.configure(mock_config)

        assert service._config == mock_config
        assert service._service is not None


class TestDoctorServiceWrapper:
    """Tests for DoctorServiceWrapper."""

    def test_check_controller_returns_report(self) -> None:
        """Test that check_controller returns a DoctorReport."""
        from lb_gui.services.doctor_service import DoctorServiceWrapper

        service = DoctorServiceWrapper()
        mock_report = MagicMock()
        service._service.check_controller = MagicMock(return_value=mock_report)

        result = service.check_controller()

        service._service.check_controller.assert_called_once()
        assert result == mock_report

    def test_run_all_checks_without_config(self) -> None:
        """Test run_all_checks without config skips connectivity."""
        from lb_gui.services.doctor_service import DoctorServiceWrapper

        service = DoctorServiceWrapper()
        mock_report1 = MagicMock()
        mock_report2 = MagicMock()
        service._service.check_controller = MagicMock(return_value=mock_report1)
        service._service.check_local_tools = MagicMock(return_value=mock_report2)

        results = service.run_all_checks()

        assert len(results) == 2
        assert mock_report1 in results
        assert mock_report2 in results

    def test_run_all_checks_with_config(self) -> None:
        """Test run_all_checks with config includes connectivity."""
        from lb_gui.services.doctor_service import DoctorServiceWrapper

        service = DoctorServiceWrapper()
        mock_report1 = MagicMock()
        mock_report2 = MagicMock()
        mock_report3 = MagicMock()
        mock_config = MagicMock()

        service._service.check_controller = MagicMock(return_value=mock_report1)
        service._service.check_local_tools = MagicMock(return_value=mock_report2)
        service._service.check_connectivity = MagicMock(return_value=mock_report3)

        results = service.run_all_checks(config=mock_config)

        assert len(results) == 3
        service._service.check_connectivity.assert_called_once_with(mock_config)


class TestAnalyticsServiceWrapper:
    """Tests for AnalyticsServiceWrapper."""

    def test_run_analytics_builds_request(self) -> None:
        """Test that run_analytics builds AnalyticsRequest correctly."""
        from lb_gui.services.analytics_service import AnalyticsServiceWrapper

        service = AnalyticsServiceWrapper()
        expected_paths = [Path("/output/report.html")]
        service._service.run = MagicMock(return_value=expected_paths)

        # Create a mock RunInfo
        mock_run_info = MagicMock()
        mock_run_info.run_id = "run1"

        result = service.run_analytics(
            run_info=mock_run_info,
            workloads=["stress_ng"],
            hosts=["host1"],
        )

        service._service.run.assert_called_once()
        call_args = service._service.run.call_args[0][0]
        assert call_args.run == mock_run_info
        assert call_args.workloads == ["stress_ng"]
        assert call_args.hosts == ["host1"]
        assert result == expected_paths

    def test_get_available_kinds(self) -> None:
        """Test that get_available_kinds returns all AnalyticsKind values."""
        from lb_gui.services.analytics_service import AnalyticsServiceWrapper
        from lb_app.api import AnalyticsKind

        service = AnalyticsServiceWrapper()
        kinds = service.get_available_kinds()

        assert kinds == list(AnalyticsKind)
