"""Unit tests for ControllerServices."""

from unittest.mock import MagicMock

from lb_controller.services.services import ControllerServices
from lb_runner.api import BenchmarkConfig


def test_controller_services_initialization():
    """Test that ControllerServices initializes correctly with provided dependencies."""
    config = BenchmarkConfig()
    executor = MagicMock()
    output_formatter = MagicMock()
    stop_token = MagicMock()
    lifecycle = MagicMock()
    journal_refresh = MagicMock()

    services = ControllerServices(
        config=config,
        executor=executor,
        output_formatter=output_formatter,
        stop_token=stop_token,
        lifecycle=lifecycle,
        journal_refresh=journal_refresh,
        use_progress_stream=False,
    )

    assert services.config is config
    assert services.executor is executor
    assert services.output_formatter is output_formatter
    assert services.stop_token is stop_token
    assert services.lifecycle is lifecycle
    assert services.journal_refresh is journal_refresh
    assert services.use_progress_stream is False


def test_controller_services_defaults():
    """Test defaults for optional arguments in ControllerServices."""
    config = BenchmarkConfig()
    executor = MagicMock()

    services = ControllerServices(config=config, executor=executor)

    assert services.config is config
    assert services.executor is executor
    assert services.output_formatter is None
    assert services.stop_token is None
    assert services.lifecycle is not None
    assert services.journal_refresh is None
    assert services.use_progress_stream is True
