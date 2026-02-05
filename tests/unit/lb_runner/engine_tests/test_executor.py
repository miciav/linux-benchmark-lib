"""Unit tests for RepetitionExecutor."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from lb_common.errors import WorkloadError
from lb_runner.engine.executor import RepetitionExecutor
from lb_runner.engine.execution import StopRequested
from lb_runner.engine.context import RunnerContext

pytestmark = [pytest.mark.unit, pytest.mark.unit_runner]


@pytest.fixture
def mock_config():
    config = MagicMock()
    config.warmup_seconds = 0
    config.output_dir = "dummy_output"
    return config


@pytest.fixture
def mock_metric_manager():
    return MagicMock()


@pytest.fixture
def mock_output_manager():
    return MagicMock()


@pytest.fixture
def mock_log_manager():
    return MagicMock()


@pytest.fixture
def context(mock_config, mock_metric_manager, mock_output_manager, mock_log_manager):
    return RunnerContext(
        run_id="run-1",
        config=mock_config,
        output_manager=mock_output_manager,
        log_manager=mock_log_manager,
        metric_manager=mock_metric_manager,
    )


@pytest.fixture
def executor(context):
    return RepetitionExecutor(context)


def test_execute_success(executor, context):
    """Test successful execution of a test repetition."""
    generator = MagicMock()
    generator.get_result.return_value = {"status": "ok"}

    metric_session = MagicMock()
    metric_session.collectors = ["collector1"]
    context.metric_manager.begin_repetition.return_value = metric_session
    context.output_manager.workload_output_dir.return_value = MagicMock()

    # Mock resolve_duration
    with patch("lb_runner.engine.executor.resolve_duration", return_value=1):
        with patch(
            "lb_runner.engine.executor.wait_for_generator", return_value=datetime.now()
        ):
            result = executor.execute("test_workload", generator, 1, 3)

    assert result["generator_result"] == {"status": "ok"}
    assert generator.start.called
    assert metric_session.start.called
    assert metric_session.stop.called
    assert metric_session.collect.called
    assert metric_session.close.called
    assert context.output_manager.persist_rep_result.called


def test_execute_stop_requested(executor, context):
    """Test execution when stop is requested."""
    generator = MagicMock()
    stop_token = MagicMock()
    stop_token.should_stop.return_value = True
    context.stop_token = stop_token
    metric_session = MagicMock()
    metric_session.collectors = []
    context.metric_manager.begin_repetition.return_value = metric_session

    # Mock resolve_duration
    with patch("lb_runner.engine.executor.resolve_duration", return_value=1):
        with pytest.raises(StopRequested):
            executor.execute("test_workload", generator, 1, 3)

    assert not generator.start.called
    # Cleanup should still be called
    assert metric_session.stop.called
    assert metric_session.close.called


def test_execute_generator_failure(executor, context):
    """Test execution when generator fails."""
    generator = MagicMock()
    generator.start.side_effect = RuntimeError("Generator crashed")
    metric_session = MagicMock()
    metric_session.collectors = []
    context.metric_manager.begin_repetition.return_value = metric_session

    with patch("lb_runner.engine.executor.resolve_duration", return_value=1):
        with pytest.raises(WorkloadError):
            executor.execute("test_workload", generator, 1, 3)

    assert metric_session.stop.called
    assert metric_session.close.called


def test_run_attempt_handles_lb_error(executor, context, tmp_path):
    generator = MagicMock()
    generator.get_result.return_value = {"returncode": 1}
    context.output_manager.workload_output_dir.return_value = tmp_path / "workload"

    with patch.object(executor, "execute", side_effect=WorkloadError("boom")):
        outcome = executor.run_attempt(
            test_name="test_workload",
            generator=generator,
            repetition=1,
            total_repetitions=1,
        )

    assert outcome.success is False
    assert outcome.status == "failed"
    assert context.output_manager.persist_rep_result.called
    assert context.output_manager.process_results.called
