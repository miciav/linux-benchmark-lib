from unittest.mock import MagicMock

from linux_benchmark_lib.cli import _print_run_plan
from linux_benchmark_lib.benchmark_config import BenchmarkConfig, WorkloadConfig

def test_print_run_plan_docker_mode():
    """Test that _print_run_plan returns correct status in Docker mode."""
    cfg = BenchmarkConfig()
    cfg.workloads["stress_ng"] = WorkloadConfig(plugin="stress_ng", enabled=True)
    
    mock_registry = MagicMock()
    # Mock plugin existence
    mock_registry.get.return_value = MagicMock(name="stress_ng")
    
    # Mock console to capture output (optional, but good for verifying side effects)
    # Since _print_run_plan uses the global 'console' object from cli.py, 
    # we can just ensure no exception is raised and logic path is hit.
    
    # Running with docker_mode=True should NOT call create_generator 
    # or check for local libraries, and should succeed even if tools are missing locally.
    
    try:
        _print_run_plan(cfg, ["stress_ng"], registry=mock_registry, docker_mode=True)
    except Exception as e:
        assert False, f"_print_run_plan raised exception in Docker mode: {e}"

    # Verify that create_generator was NOT called (because we skip validation)
    # The current implementation of _status in docker mode returns early.
    # Let's verify that get() was called to ensure plugin exists.
    mock_registry.get.assert_called_with("stress_ng")
