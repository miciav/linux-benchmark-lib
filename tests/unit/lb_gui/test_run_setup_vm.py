"""Unit tests for RunSetupViewModel."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest


class TestRunSetupViewModel:
    """Tests for RunSetupViewModel."""

    @pytest.fixture
    def mock_services(self) -> tuple[MagicMock, MagicMock]:
        """Create mock plugin and config services."""
        plugin_service = MagicMock()
        config_service = MagicMock()
        return plugin_service, config_service

    def test_initial_state(self, mock_services: tuple[MagicMock, MagicMock]) -> None:
        """Test initial viewmodel state."""
        from lb_gui.viewmodels.run_setup_vm import RunSetupViewModel

        plugin_service, config_service = mock_services
        vm = RunSetupViewModel(plugin_service, config_service)

        assert vm.config is None
        assert vm.available_workloads == []
        assert vm.selected_workloads == []
        assert vm.intensity == "medium"
        assert vm.repetitions == 1
        assert vm.execution_mode == "remote"
        assert vm.node_count == 1

    def test_intensity_setter_validates(
        self, mock_services: tuple[MagicMock, MagicMock]
    ) -> None:
        """Test that intensity setter validates values."""
        from lb_gui.viewmodels.run_setup_vm import RunSetupViewModel

        plugin_service, config_service = mock_services
        vm = RunSetupViewModel(plugin_service, config_service)

        vm.intensity = "high"
        assert vm.intensity == "high"

        vm.intensity = "invalid"
        assert vm.intensity == "high"  # Unchanged

    def test_repetitions_setter_enforces_minimum(
        self, mock_services: tuple[MagicMock, MagicMock]
    ) -> None:
        """Test that repetitions cannot be less than 1."""
        from lb_gui.viewmodels.run_setup_vm import RunSetupViewModel

        plugin_service, config_service = mock_services
        vm = RunSetupViewModel(plugin_service, config_service)

        vm.repetitions = 0
        assert vm.repetitions == 1

        vm.repetitions = -5
        assert vm.repetitions == 1

        vm.repetitions = 10
        assert vm.repetitions == 10

    def test_execution_mode_setter_validates(
        self, mock_services: tuple[MagicMock, MagicMock]
    ) -> None:
        """Test that execution mode setter validates values."""
        from lb_gui.viewmodels.run_setup_vm import RunSetupViewModel

        plugin_service, config_service = mock_services
        vm = RunSetupViewModel(plugin_service, config_service)

        vm.execution_mode = "docker"
        assert vm.execution_mode == "docker"

        vm.execution_mode = "invalid"
        assert vm.execution_mode == "docker"  # Unchanged

    def test_node_count_enforces_bounds(
        self, mock_services: tuple[MagicMock, MagicMock]
    ) -> None:
        """Test that node count is bounded by 1 and MAX_NODES."""
        from lb_gui.viewmodels.run_setup_vm import RunSetupViewModel

        plugin_service, config_service = mock_services
        vm = RunSetupViewModel(plugin_service, config_service)

        vm.node_count = 0
        assert vm.node_count == 1

        vm.node_count = 100
        assert vm.node_count == vm.max_nodes

    def test_node_count_enabled_for_docker_multipass(
        self, mock_services: tuple[MagicMock, MagicMock]
    ) -> None:
        """Test node_count_enabled property."""
        from lb_gui.viewmodels.run_setup_vm import RunSetupViewModel

        plugin_service, config_service = mock_services
        vm = RunSetupViewModel(plugin_service, config_service)

        vm.execution_mode = "remote"
        assert vm.node_count_enabled is False

        vm.execution_mode = "docker"
        assert vm.node_count_enabled is True

        vm.execution_mode = "multipass"
        assert vm.node_count_enabled is True

    def test_validate_requires_config(
        self, mock_services: tuple[MagicMock, MagicMock]
    ) -> None:
        """Test validation fails without config."""
        from lb_gui.viewmodels.run_setup_vm import RunSetupViewModel

        plugin_service, config_service = mock_services
        vm = RunSetupViewModel(plugin_service, config_service)

        is_valid, error = vm.validate()
        assert is_valid is False
        assert "configuration" in error.lower()

    def test_validate_requires_workloads(
        self, mock_services: tuple[MagicMock, MagicMock]
    ) -> None:
        """Test validation fails without selected workloads."""
        from lb_gui.viewmodels.run_setup_vm import RunSetupViewModel

        plugin_service, config_service = mock_services
        vm = RunSetupViewModel(plugin_service, config_service)
        vm._config = MagicMock()
        vm._config.remote_hosts = ["host1"]

        is_valid, error = vm.validate()
        assert is_valid is False
        assert "workloads" in error.lower()

    def test_validate_remote_requires_hosts(
        self, mock_services: tuple[MagicMock, MagicMock]
    ) -> None:
        """Test validation fails for remote mode without hosts."""
        from lb_gui.viewmodels.run_setup_vm import RunSetupViewModel

        plugin_service, config_service = mock_services
        vm = RunSetupViewModel(plugin_service, config_service)
        vm._config = MagicMock()
        vm._config.remote_hosts = []
        vm._selected_workloads = ["stress_ng"]
        vm._execution_mode = "remote"

        is_valid, error = vm.validate()
        assert is_valid is False
        assert "remote hosts" in error.lower()

    def test_validate_passes_with_valid_state(
        self, mock_services: tuple[MagicMock, MagicMock]
    ) -> None:
        """Test validation passes with valid configuration."""
        from lb_gui.viewmodels.run_setup_vm import RunSetupViewModel

        plugin_service, config_service = mock_services
        vm = RunSetupViewModel(plugin_service, config_service)
        vm._config = MagicMock()
        vm._config.remote_hosts = ["host1"]
        vm._selected_workloads = ["stress_ng"]
        vm._execution_mode = "remote"

        is_valid, error = vm.validate()
        assert is_valid is True
        assert error == ""

    def test_build_run_request_returns_none_if_invalid(
        self, mock_services: tuple[MagicMock, MagicMock]
    ) -> None:
        """Test build_run_request returns None for invalid state."""
        from lb_gui.viewmodels.run_setup_vm import RunSetupViewModel

        plugin_service, config_service = mock_services
        vm = RunSetupViewModel(plugin_service, config_service)

        request = vm.build_run_request()
        assert request is None

    def test_build_run_request_creates_request(
        self, mock_services: tuple[MagicMock, MagicMock]
    ) -> None:
        """Test build_run_request creates valid RunRequest."""
        from lb_gui.viewmodels.run_setup_vm import RunSetupViewModel

        plugin_service, config_service = mock_services
        vm = RunSetupViewModel(plugin_service, config_service)

        mock_config = MagicMock()
        mock_config.remote_hosts = ["host1"]
        vm._config = mock_config
        vm._selected_workloads = ["stress_ng", "fio"]
        vm._intensity = "high"
        vm._repetitions = 3
        vm._execution_mode = "docker"
        vm._node_count = 2
        vm._run_id = "test-run"

        request = vm.build_run_request()

        assert request is not None
        assert request.config == mock_config
        assert request.tests == ["stress_ng", "fio"]
        assert request.intensity == "high"
        assert request.repetitions == 3
        assert request.execution_mode == "docker"
        assert request.node_count == 2
        assert request.run_id == "test-run"

    def test_build_run_request_generates_run_id_and_stop_file(
        self, mock_services: tuple[MagicMock, MagicMock]
    ) -> None:
        """Test build_run_request generates run_id and stop_file when missing."""
        from lb_gui.viewmodels.run_setup_vm import RunSetupViewModel

        plugin_service, config_service = mock_services
        vm = RunSetupViewModel(plugin_service, config_service)

        mock_config = MagicMock()
        mock_config.remote_hosts = ["host1"]
        mock_config.output_dir = Path("/tmp/benchmark_results")
        vm._config = mock_config
        vm._selected_workloads = ["stress_ng"]
        vm._execution_mode = "remote"
        vm._run_id = ""
        vm._stop_file = ""

        request = vm.build_run_request()

        assert request is not None
        assert request.run_id
        assert request.stop_file == Path("/tmp/benchmark_results") / request.run_id / "STOP"

    def test_refresh_workloads_loads_enabled_plugins(
        self, mock_services: tuple[MagicMock, MagicMock]
    ) -> None:
        """Test refresh_workloads populates available_workloads."""
        from lb_gui.viewmodels.run_setup_vm import RunSetupViewModel

        plugin_service, config_service = mock_services

        # Setup mock registry
        mock_registry = MagicMock()
        mock_registry.available.return_value = {"stress_ng": MagicMock(), "fio": MagicMock()}
        plugin_service.get_registry.return_value = mock_registry

        # Setup mock platform config
        mock_platform = MagicMock()
        mock_platform.is_plugin_enabled.side_effect = lambda name: name == "stress_ng"
        config_service.load_platform_config.return_value = (mock_platform, Path("/path"), True)

        vm = RunSetupViewModel(plugin_service, config_service)
        vm.refresh_workloads()

        assert "stress_ng" in vm.available_workloads
        assert "fio" not in vm.available_workloads  # Disabled
