import pytest

from lb_ui.cli import _print_run_plan
from lb_runner.benchmark_config import BenchmarkConfig, WorkloadConfig

pytestmark = [pytest.mark.ui, pytest.mark.ui]


def test_print_run_plan_docker_mode(capsys: pytest.CaptureFixture[str]):
    """Test that _print_run_plan returns correct status in Docker mode."""
    cfg = BenchmarkConfig()
    cfg.workloads["stress_ng"] = WorkloadConfig(plugin="stress_ng", enabled=True)

    _print_run_plan(cfg, ["stress_ng"], execution_mode="docker")

    out = capsys.readouterr().out
    assert "stress_ng" in out
    assert "Docker" in out or "docker" in out
