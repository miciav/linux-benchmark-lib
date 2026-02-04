from unittest.mock import MagicMock

from lb_runner.api import BenchmarkConfig
from lb_runner.engine.metrics import MetricManager


def test_collectors_disabled_skips_registry() -> None:
    registry = MagicMock()
    registry.create_collectors.side_effect = AssertionError("should not be called")
    metric_manager = MetricManager(
        registry=registry,
        output_manager=MagicMock(),
        host_name="host",
    )

    session = metric_manager.begin_repetition(
        BenchmarkConfig(),
        test_name="dummy",
        repetition=1,
        total_repetitions=1,
        current_run_id="run-1",
        collectors_enabled=False,
    )

    assert session.collectors == []
