import pytest
from unittest.mock import MagicMock, ANY, patch
from pathlib import Path

from lb_controller.services.run_service import RunService, RunContext, RunStatus
from lb_runner.benchmark_config import BenchmarkConfig, WorkloadConfig, RemoteExecutionConfig
from lb_controller.services.config_service import ConfigService
from lb_ui.ui.types import UIAdapter

@pytest.fixture
def mock_registry():
    registry = MagicMock()
    registry.available.return_value = {}
    return registry

@pytest.fixture
def mock_registry_factory(mock_registry):
    return lambda: mock_registry

@pytest.fixture
def run_service(mock_registry_factory):
    return RunService(registry_factory=mock_registry_factory)

@pytest.fixture
def mock_config_service():
    service = MagicMock(spec=ConfigService)
    cfg = BenchmarkConfig()
    cfg.workloads = {
        "stress_ng": WorkloadConfig(plugin="stress_ng", enabled=True),
        "fio": WorkloadConfig(plugin="fio", enabled=False),
    }
    service.load_for_read.return_value = (cfg, Path("/tmp/cfg.json"), None)
    return service

@pytest.fixture
def mock_ui():
    return MagicMock(spec=UIAdapter)

def test_create_session_basic(run_service, mock_config_service):
    """Test basic session creation with default config."""
    context = run_service.create_session(mock_config_service)
    
    assert isinstance(context, RunContext)
    assert context.target_tests == ["stress_ng"]  # Only enabled ones
    assert context.config_path == Path("/tmp/cfg.json")
    assert not context.use_remote
    assert not context.use_container

def test_create_session_overrides(run_service, mock_config_service, mock_ui):
    """Test repetitions and intensity overrides."""
    context = run_service.create_session(
        mock_config_service,
        repetitions=5,
        intensity="high",
        ui_adapter=mock_ui
    )
    
    assert context.config.repetitions == 5
    # Intensity override check (requires inspection of workloads)
    assert context.config.workloads["stress_ng"].intensity == "high"
    assert context.config.workloads["fio"].intensity == "high"
    
    # UI should have been notified
    mock_ui.show_info.assert_any_call("Using 5 repetitions for this run")
    mock_ui.show_info.assert_any_call("Global intensity override: high")

def test_create_session_explicit_tests(run_service, mock_config_service):
    """Test explicit test selection overriding enabled status."""
    context = run_service.create_session(
        mock_config_service,
        tests=["fio"]
    )
    assert context.target_tests == ["fio"]

def test_create_session_multipass_implies_remote(run_service, mock_config_service):
    """Test that multipass=True forces use_remote=True."""
    context = run_service.create_session(
        mock_config_service,
        multipass=True,
        multipass_vm_count=3
    )
    assert context.use_multipass is True
    assert context.use_remote is True
    assert context.multipass_count == 3

def test_create_session_docker_options(run_service, mock_config_service):
    """Test mapping of docker options to context."""
    context = run_service.create_session(
        mock_config_service,
        docker=True,
        docker_image="custom:tag",
        docker_engine="podman",
        docker_no_build=True,
        docker_no_cache=True
    )
    assert context.use_container is True
    assert context.docker_image == "custom:tag"
    assert context.docker_engine == "podman"
    assert context.docker_build is False  # no_build=True -> build=False
    assert context.docker_no_cache is True

def test_create_session_setup_flag(run_service, mock_config_service):
    """Test that the setup CLI flag overrides the config."""
    # Test default setup=True (signature default)
    context = run_service.create_session(mock_config_service)
    assert context.config.remote_execution.run_setup is True
    assert context.config.remote_execution.run_teardown is True

    # Test setup=False
    context = run_service.create_session(mock_config_service, setup=False)
    assert context.config.remote_execution.run_setup is False
    assert context.config.remote_execution.run_teardown is False

def test_create_session_no_workloads_error(run_service, mock_config_service):
    """Test validation error when no workloads are selected."""
    # Disable all workloads
    cfg = mock_config_service.load_for_read.return_value[0]
    for wl in cfg.workloads.values():
        wl.enabled = False
        
    with pytest.raises(ValueError, match="No workloads selected"):
        run_service.create_session(mock_config_service)

def test_execute_local_with_setup(run_service, mock_config_service, mock_registry):
    """Test that local execution calls SetupService when configured."""
    mock_setup = run_service._setup_service
    mock_setup.provision_global = MagicMock(return_value=True)
    mock_setup.provision_workload = MagicMock(return_value=True)
    mock_setup.teardown_workload = MagicMock(return_value=True)
    mock_setup.teardown_global = MagicMock(return_value=True)
    
    # Mock LocalRunner to avoid real execution
    with patch("lb_controller.services.run_service.LocalRunner") as MockRunner:
        mock_runner_instance = MockRunner.return_value
        mock_runner_instance.run_benchmark.return_value = True
        
        # Create session with setup=True (default)
        context = run_service.create_session(mock_config_service, setup=True)
        # Mock registry to return a dummy plugin
        mock_registry.get.return_value = MagicMock()
        
        run_service.execute(context, run_id="test_run")
        
        # Verify interactions
        mock_setup.provision_global.assert_called_once()
        mock_setup.provision_workload.assert_called()
        mock_runner_instance.run_benchmark.assert_called()
        # Teardown logic is conditional on config.run_teardown which defaults to False/None in mock
        # Let's assume defaults. If we want to test teardown, we should set it in config.

    def test_execute_local_skips_on_setup_failure(run_service, mock_config_service, mock_registry, mock_ui):
        """Test that workload execution is skipped if per-workload setup fails."""
        mock_setup = run_service._setup_service
        mock_setup.provision_global = MagicMock(return_value=True)
        mock_setup.provision_workload = MagicMock(return_value=False) # Fail setup
        mock_setup.teardown_workload = MagicMock(return_value=True) # Prevent real call
        mock_setup.teardown_global = MagicMock(return_value=True)   # Prevent real call
        
        with patch("lb_controller.services.run_service.LocalRunner") as MockRunner:
            mock_runner_instance = MockRunner.return_value
            
            context = run_service.create_session(mock_config_service, setup=True, ui_adapter=mock_ui)
            run_service.execute(context, run_id="test_run", ui_adapter=mock_ui)
            
            mock_setup.provision_workload.assert_called()
            # Should NOT run benchmark
            mock_runner_instance.run_benchmark.assert_not_called()
            # Should show error
            mock_ui.show_error.assert_any_call(ANY) # Check for error message match if desired


def test_parse_progress_line():
    service = RunService(lambda: MagicMock())
    line = 'LB_EVENT {"host": "node1", "workload": "geekbench", "repetition": 2, "total_repetitions": 3, "status": "running"}'
    parsed = service._parse_progress_line(line)
    assert parsed == {
        "host": "node1",
        "workload": "geekbench",
        "rep": 2,
        "status": "running",
        "total": 3,
        "message": None,
    }

def test_parse_progress_line_escaped():
    service = RunService(lambda: MagicMock())
    line = '    "msg": "LB_EVENT {\\"host\\": \\"node1\\", \\"workload\\": \\"geekbench\\", \\"repetition\\": 2, \\"total_repetitions\\": 3, \\"status\\": \\"running\\"}"'
    parsed = service._parse_progress_line(line)
    assert parsed == {
        "host": "node1",
        "workload": "geekbench",
        "rep": 2,
        "status": "running",
        "total": 3,
        "message": None,
    }
