import logging
from unittest.mock import MagicMock


def test_logger_adapter_propagates_phase_context() -> None:
    """LoggerAdapter should inject lb_phase into LogRecord."""
    logger = logging.getLogger("test.adapter")
    handler = MagicMock()
    handler.level = logging.NOTSET
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    adapter = logging.LoggerAdapter(logger, {"lb_phase": "setup"})

    adapter.info("test message")

    assert handler.handle.called
    record = handler.handle.call_args[0][0]
    assert record.msg == "test message"
    assert getattr(record, "lb_phase", None) == "setup"


def test_logger_adapter_propagates_multiple_context_attributes() -> None:
    """LoggerAdapter should propagate multiple attributes from context."""
    logger = logging.getLogger("test.adapter.extra")
    handler = MagicMock()
    handler.level = logging.NOTSET
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    adapter = logging.LoggerAdapter(
        logger, {"lb_phase": "run", "lb_workload": "stress"}
    )

    adapter.info("test message")

    assert handler.handle.called
    record = handler.handle.call_args[0][0]
    assert getattr(record, "lb_phase", None) == "run"
    assert getattr(record, "lb_workload", None) == "stress"
