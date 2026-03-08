from __future__ import annotations

import logging
from unittest.mock import MagicMock, Mock

import pytest

from lb_plugins.plugins.dfaas.config import DfaasConfig
from lb_plugins.plugins.dfaas.context import ExecutionContext
from lb_plugins.plugins.dfaas.services.log_manager import DfaasLogManager
from lb_runner.api import LBEventLogHandler

pytestmark = [pytest.mark.unit_plugins]


def _make_manager(
    *,
    event_logging_enabled: bool,
    logger: MagicMock | None = None,
    k6_logger: MagicMock | None = None,
    event_emitter: Mock | None = None,
) -> DfaasLogManager:
    return DfaasLogManager(
        config=DfaasConfig(),
        exec_ctx=ExecutionContext(
            host="node-1",
            repetition=2,
            total_repetitions=4,
            event_logging_enabled=event_logging_enabled,
        ),
        logger=logger or MagicMock(spec=logging.Logger),
        k6_logger=k6_logger or MagicMock(spec=logging.Logger),
        event_emitter=event_emitter or Mock(),
    )


def test_emit_log_skips_lb_event_when_matching_root_handler_present() -> None:
    manager = _make_manager(event_logging_enabled=True)
    manager.set_run_id("run-2")

    root_logger = logging.getLogger()
    lb_handler = LBEventLogHandler(
        run_id="run-2",
        host="node-1",
        workload="dfaas",
        repetition=2,
        total_repetitions=4,
    )
    root_logger.addHandler(lb_handler)
    try:
        manager.emit_log("hello")
    finally:
        root_logger.removeHandler(lb_handler)

    manager.event_emitter.emit.assert_not_called()
    manager.logger.log.assert_called_once()


def test_emit_log_keeps_lb_event_when_root_handler_belongs_to_other_run() -> None:
    manager = _make_manager(event_logging_enabled=True)
    manager.set_run_id("run-2")

    root_logger = logging.getLogger()
    foreign_handler = LBEventLogHandler(
        run_id="run-foreign",
        host="node-9",
        workload="other",
        repetition=99,
        total_repetitions=99,
    )
    root_logger.addHandler(foreign_handler)
    try:
        manager.emit_log("hello")
    finally:
        root_logger.removeHandler(foreign_handler)

    manager.event_emitter.emit.assert_called_once()
    manager.logger.log.assert_not_called()
