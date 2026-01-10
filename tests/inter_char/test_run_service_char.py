import pytest
from unittest.mock import MagicMock, ANY

from lb_app.services.run_service import RunService
from lb_controller.api import BenchmarkConfig, WorkloadConfig
from lb_runner.api import RemoteHostConfig
from lb_plugins.api import PluginRegistry

@pytest.fixture
def mock_registry():
    registry = MagicMock(spec=PluginRegistry)
    registry.plugins = {"stress_ng": MagicMock()}
    return registry

@pytest.fixture
def run_service(mock_registry):
    return RunService(lambda: mock_registry)

@pytest.mark.inter_generic
def test_char_run_benchmark_local_flow(run_service, mock_registry, tmp_path, monkeypatch):
    """
    Characterization test for local benchmark run.
    Verifies that run_benchmark orchestrates the components correctly.
    """
    # 1. Setup Config
    cfg = BenchmarkConfig(
        output_dir=str(tmp_path),
        workloads={"stress": WorkloadConfig(plugin="stress_ng")},
        remote_hosts=[
            RemoteHostConfig(name="localhost", address="127.0.0.1", user="root", become=False)
        ]
    )
    
    # 2. Mock Internal Methods
    # Since RunService uses _run_remote for everything (controller-based),
    # we spy on that.
    mock_run_remote = MagicMock(return_value=MagicMock(success=True))
    monkeypatch.setattr(run_service, "_run_remote", mock_run_remote)
    
    mock_ui = MagicMock()
    
    # 3. Execute with execution_mode="local"
    # Note: run_benchmark isn't a method on RunService (my bad assumption).
    # It seems consumers use run_service.create_session() + run_service.execute().
    # Let's verify the 'execute' flow.
    
    context = run_service.build_context(
        cfg, 
        tests=["stress"], 
        execution_mode="local"
    )
    
    run_service.execute(
        context=context,
        run_id="test_run",
        ui_adapter=mock_ui
    )
    
    # 4. Verify
    mock_run_remote.assert_called_once()
    call_args = mock_run_remote.call_args
    assert call_args.args[0] == context # context is first arg
    assert context.execution_mode == "local"


@pytest.mark.inter_generic
def test_char_run_benchmark_remote_flow(run_service, mock_registry, tmp_path, monkeypatch):
    """
    Characterization test for remote benchmark run.
    """
    # 1. Setup Config
    cfg = BenchmarkConfig(
        output_dir=str(tmp_path),
        workloads={"stress": WorkloadConfig(plugin="stress_ng")},
        remote_hosts=[
            RemoteHostConfig(name="host1", address="192.168.1.10", user="user", become=True)
        ]
    )
    
    # 2. Mock Internal Methods
    mock_run_remote = MagicMock(return_value=MagicMock(success=True))
    monkeypatch.setattr(run_service, "_run_remote", mock_run_remote)
    
    mock_ui = MagicMock()
    
    # 3. Execute
    context = run_service.build_context(
        cfg, 
        tests=["stress"], 
        execution_mode="remote"
    )
    
    run_service.execute(
        context=context,
        run_id="test_run_remote",
        ui_adapter=mock_ui
    )
    
    # 4. Verify
    mock_run_remote.assert_called_once()
    ctx_arg = mock_run_remote.call_args.args[0]
    assert ctx_arg.execution_mode == "remote"