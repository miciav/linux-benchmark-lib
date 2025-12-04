import pytest
from unittest.mock import MagicMock, ANY
from pathlib import Path

from linux_benchmark_lib.services.run_service import RunService, RunContext
from linux_benchmark_lib.benchmark_config import BenchmarkConfig, WorkloadConfig, RemoteExecutionConfig
from linux_benchmark_lib.services.config_service import ConfigService
from linux_benchmark_lib.ui.types import UIAdapter

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

def test_create_session_no_workloads_error(run_service, mock_config_service):
    """Test validation error when no workloads are selected."""
    # Disable all workloads
    cfg = mock_config_service.load_for_read.return_value[0]
    for wl in cfg.workloads.values():
        wl.enabled = False
        
    with pytest.raises(ValueError, match="No workloads selected"):
        run_service.create_session(mock_config_service)
