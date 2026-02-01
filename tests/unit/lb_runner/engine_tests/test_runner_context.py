"""Unit tests for RunnerContext."""

from unittest.mock import MagicMock

import pytest

from lb_runner.engine.context import RunnerContext


pytestmark = [pytest.mark.unit, pytest.mark.unit_runner]


class TestRunnerContextCreation:
    """Tests for RunnerContext instantiation."""

    def test_creates_with_required_fields(self) -> None:
        """RunnerContext can be created with all required fields."""
        ctx = RunnerContext(
            run_id="test-run-1",
            config=MagicMock(),
            output_manager=MagicMock(),
            log_manager=MagicMock(),
            metric_manager=MagicMock(),
        )
        assert ctx.run_id == "test-run-1"
        assert ctx.stop_token is None
        assert ctx.host_name is None

    def test_creates_with_optional_fields(self) -> None:
        """RunnerContext accepts optional stop_token and host_name."""
        stop_token = MagicMock()
        ctx = RunnerContext(
            run_id="test-run-2",
            config=MagicMock(),
            output_manager=MagicMock(),
            log_manager=MagicMock(),
            metric_manager=MagicMock(),
            stop_token=stop_token,
            host_name="node-1",
        )
        assert ctx.stop_token is stop_token
        assert ctx.host_name == "node-1"

    def test_run_id_can_be_none(self) -> None:
        """RunnerContext allows None run_id."""
        ctx = RunnerContext(
            run_id=None,
            config=MagicMock(),
            output_manager=MagicMock(),
            log_manager=MagicMock(),
            metric_manager=MagicMock(),
        )
        assert ctx.run_id is None


class TestRunnerContextAccess:
    """Tests for accessing RunnerContext attributes."""

    def test_config_accessible(self) -> None:
        """Config should be accessible from context."""
        config = MagicMock()
        config.warmup_seconds = 5
        ctx = RunnerContext(
            run_id="test",
            config=config,
            output_manager=MagicMock(),
            log_manager=MagicMock(),
            metric_manager=MagicMock(),
        )
        assert ctx.config.warmup_seconds == 5

    def test_managers_accessible(self) -> None:
        """All managers should be accessible from context."""
        output_mgr = MagicMock()
        log_mgr = MagicMock()
        metric_mgr = MagicMock()

        ctx = RunnerContext(
            run_id="test",
            config=MagicMock(),
            output_manager=output_mgr,
            log_manager=log_mgr,
            metric_manager=metric_mgr,
        )

        assert ctx.output_manager is output_mgr
        assert ctx.log_manager is log_mgr
        assert ctx.metric_manager is metric_mgr
