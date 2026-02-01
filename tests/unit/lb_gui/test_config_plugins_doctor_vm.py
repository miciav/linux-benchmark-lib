"""Unit tests for Config, Plugins, and Doctor ViewModels."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest


class TestConfigViewModel:
    """Tests for ConfigViewModel."""

    @pytest.fixture
    def mock_config_service(self) -> MagicMock:
        """Create mock config service."""
        return MagicMock()

    def test_initial_state(self, mock_config_service: MagicMock) -> None:
        """Test initial viewmodel state."""
        from lb_gui.viewmodels.config_vm import ConfigViewModel

        vm = ConfigViewModel(mock_config_service)

        assert vm.config is None
        assert vm.config_path is None
        assert vm.is_dirty is False
        assert vm.is_loaded is False

    def test_load_config_success(self, mock_config_service: MagicMock) -> None:
        """Test successful config loading."""
        from lb_gui.viewmodels.config_vm import ConfigViewModel

        mock_config = MagicMock()
        mock_config_service.load_config.return_value = (
            mock_config,
            Path("/config.yaml"),
            None,
        )

        vm = ConfigViewModel(mock_config_service)
        result = vm.load_config(Path("/config.yaml"))

        assert result is True
        assert vm.config == mock_config
        assert vm.config_path == Path("/config.yaml")
        assert vm.is_loaded is True

    def test_load_config_failure(self, mock_config_service: MagicMock) -> None:
        """Test config loading failure."""
        from lb_gui.viewmodels.config_vm import ConfigViewModel

        mock_config_service.load_config.side_effect = Exception("Load error")

        vm = ConfigViewModel(mock_config_service)
        result = vm.load_config()

        assert result is False
        assert vm.is_loaded is False

    def test_get_basic_info_empty_without_config(
        self, mock_config_service: MagicMock
    ) -> None:
        """Test get_basic_info returns empty dict without config."""
        from lb_gui.viewmodels.config_vm import ConfigViewModel

        vm = ConfigViewModel(mock_config_service)
        info = vm.get_basic_info()

        assert info == {}

    def test_get_basic_info_with_config(
        self, mock_config_service: MagicMock
    ) -> None:
        """Test get_basic_info returns config values."""
        from lb_gui.viewmodels.config_vm import ConfigViewModel

        mock_config = MagicMock()
        mock_config.repetitions = 5
        mock_config.test_duration_seconds = 3600
        mock_config.metrics_interval_seconds = 1.0
        mock_config.warmup_seconds = 10
        mock_config.cooldown_seconds = 10
        mock_config.output_dir = Path("/output")
        mock_config.report_dir = Path("/reports")
        mock_config.data_export_dir = Path("/exports")

        vm = ConfigViewModel(mock_config_service)
        vm._config = mock_config

        info = vm.get_basic_info()

        assert info["Repetitions"] == "5"
        assert info["Output Directory"] == "/output"

    def test_set_as_default_requires_loaded_config(
        self, mock_config_service: MagicMock
    ) -> None:
        """Test set_as_default fails without loaded config."""
        from lb_gui.viewmodels.config_vm import ConfigViewModel

        vm = ConfigViewModel(mock_config_service)
        result = vm.set_as_default()

        assert result is False


class TestPluginsViewModel:
    """Tests for PluginsViewModel."""

    @pytest.fixture
    def mock_services(self) -> tuple[MagicMock, MagicMock]:
        """Create mock services."""
        plugin_service = MagicMock()
        config_service = MagicMock()
        return plugin_service, config_service

    def test_initial_state(self, mock_services: tuple[MagicMock, MagicMock]) -> None:
        """Test initial viewmodel state."""
        from lb_gui.viewmodels.plugins_vm import PluginsViewModel

        plugin_service, config_service = mock_services
        vm = PluginsViewModel(plugin_service, config_service)

        assert vm.headers == []
        assert vm.rows == []

    def test_refresh_plugins_loads_data(
        self, mock_services: tuple[MagicMock, MagicMock]
    ) -> None:
        """Test refresh_plugins loads plugin data."""
        from lb_gui.viewmodels.plugins_vm import PluginsViewModel

        plugin_service, config_service = mock_services

        mock_platform = MagicMock()
        mock_platform.is_plugin_enabled.return_value = True
        config_service.load_platform_config.return_value = (mock_platform, Path("/p"), True)

        mock_registry = MagicMock()
        mock_registry.available.return_value = {"stress_ng": MagicMock()}
        plugin_service.get_registry.return_value = mock_registry
        plugin_service.get_plugin_table.return_value = (
            ["Name", "Enabled"],
            [["stress_ng", "Yes"]],
        )

        vm = PluginsViewModel(plugin_service, config_service)
        vm.refresh_plugins()

        assert vm.headers == ["Name", "Enabled"]
        assert len(vm.rows) == 1

    def test_toggle_plugin(self, mock_services: tuple[MagicMock, MagicMock]) -> None:
        """Test toggle_plugin changes enabled state."""
        from lb_gui.viewmodels.plugins_vm import PluginsViewModel

        plugin_service, config_service = mock_services

        mock_platform = MagicMock()
        mock_platform.is_plugin_enabled.return_value = True
        config_service.load_platform_config.return_value = (mock_platform, Path("/p"), True)

        mock_registry = MagicMock()
        mock_registry.available.return_value = {"stress_ng": MagicMock()}
        plugin_service.get_registry.return_value = mock_registry
        plugin_service.get_plugin_table.return_value = (["Name"], [["stress_ng"]])

        vm = PluginsViewModel(plugin_service, config_service)
        vm._enabled_map = {"stress_ng": True}

        vm.toggle_plugin("stress_ng")

        config_service.set_plugin_enabled.assert_called_once_with("stress_ng", False)

    def test_is_plugin_enabled(
        self, mock_services: tuple[MagicMock, MagicMock]
    ) -> None:
        """Test is_plugin_enabled returns correct state."""
        from lb_gui.viewmodels.plugins_vm import PluginsViewModel

        plugin_service, config_service = mock_services

        vm = PluginsViewModel(plugin_service, config_service)
        vm._enabled_map = {"stress_ng": True, "fio": False}

        assert vm.is_plugin_enabled("stress_ng") is True
        assert vm.is_plugin_enabled("fio") is False


class TestDoctorViewModel:
    """Tests for DoctorViewModel."""

    @pytest.fixture
    def mock_services(self) -> tuple[MagicMock, MagicMock]:
        """Create mock services."""
        doctor_service = MagicMock()
        config_service = MagicMock()
        return doctor_service, config_service

    @pytest.fixture
    def mock_report(self) -> MagicMock:
        """Create a mock DoctorReport."""
        report = MagicMock()
        report.total_failures = 0
        report.info_messages = ["Info 1"]

        group = MagicMock()
        group.title = "Controller"
        item = MagicMock()
        item.label = "Ansible"
        item.ok = True
        item.required = True
        group.items = [item]

        report.groups = [group]
        return report

    def test_initial_state(self, mock_services: tuple[MagicMock, MagicMock]) -> None:
        """Test initial viewmodel state."""
        from lb_gui.viewmodels.doctor_vm import DoctorViewModel

        doctor_service, config_service = mock_services
        vm = DoctorViewModel(doctor_service, config_service)

        assert vm.reports == []
        assert vm.is_running is False
        assert vm.total_failures == 0

    def test_run_all_checks_calls_service(
        self,
        mock_services: tuple[MagicMock, MagicMock],
        mock_report: MagicMock,
    ) -> None:
        """Test run_all_checks calls doctor service methods."""
        from lb_gui.viewmodels.doctor_vm import DoctorViewModel

        doctor_service, config_service = mock_services
        doctor_service.check_controller.return_value = mock_report
        doctor_service.check_local_tools.return_value = mock_report

        vm = DoctorViewModel(doctor_service, config_service)
        vm.run_all_checks()

        doctor_service.check_controller.assert_called_once()
        doctor_service.check_local_tools.assert_called_once()
        assert len(vm.reports) == 2

    def test_all_passed_property(
        self,
        mock_services: tuple[MagicMock, MagicMock],
        mock_report: MagicMock,
    ) -> None:
        """Test all_passed property."""
        from lb_gui.viewmodels.doctor_vm import DoctorViewModel

        doctor_service, config_service = mock_services

        vm = DoctorViewModel(doctor_service, config_service)
        vm._reports = [mock_report]

        assert vm.all_passed is True

    def test_all_passed_false_with_failures(
        self, mock_services: tuple[MagicMock, MagicMock]
    ) -> None:
        """Test all_passed is False when there are failures."""
        from lb_gui.viewmodels.doctor_vm import DoctorViewModel

        doctor_service, config_service = mock_services

        mock_report = MagicMock()
        mock_report.total_failures = 2
        mock_report.groups = []

        vm = DoctorViewModel(doctor_service, config_service)
        vm._reports = [mock_report]

        assert vm.all_passed is False

    def test_get_summary(
        self,
        mock_services: tuple[MagicMock, MagicMock],
        mock_report: MagicMock,
    ) -> None:
        """Test get_summary returns correct counts."""
        from lb_gui.viewmodels.doctor_vm import DoctorViewModel

        doctor_service, config_service = mock_services

        vm = DoctorViewModel(doctor_service, config_service)
        vm._reports = [mock_report]

        summary = vm.get_summary()

        assert summary["total"] == 1
        assert summary["passed"] == 1
        assert summary["failed"] == 0

    def test_get_flattened_results(
        self,
        mock_services: tuple[MagicMock, MagicMock],
        mock_report: MagicMock,
    ) -> None:
        """Test get_flattened_results returns table data."""
        from lb_gui.viewmodels.doctor_vm import DoctorViewModel

        doctor_service, config_service = mock_services

        vm = DoctorViewModel(doctor_service, config_service)
        vm._reports = [mock_report]

        results = vm.get_flattened_results()

        assert len(results) == 1
        assert results[0]["Group"] == "Controller"
        assert results[0]["Check"] == "Ansible"
        assert results[0]["Status"] == "Pass"

    def test_get_info_messages(
        self,
        mock_services: tuple[MagicMock, MagicMock],
        mock_report: MagicMock,
    ) -> None:
        """Test get_info_messages collects all messages."""
        from lb_gui.viewmodels.doctor_vm import DoctorViewModel

        doctor_service, config_service = mock_services

        vm = DoctorViewModel(doctor_service, config_service)
        vm._reports = [mock_report]

        messages = vm.get_info_messages()

        assert "Info 1" in messages
