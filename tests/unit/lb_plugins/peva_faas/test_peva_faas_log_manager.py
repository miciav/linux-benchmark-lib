from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

import lb_plugins.plugins.peva_faas.services.log_manager as log_manager_mod
from lb_plugins.plugins.peva_faas.config import DfaasConfig
from lb_plugins.plugins.peva_faas.context import ExecutionContext
from lb_plugins.plugins.peva_faas.services.log_manager import DfaasLogManager
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


def test_attach_handlers_replaces_previous_handlers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    logger = MagicMock(spec=logging.Logger)
    k6_logger = MagicMock(spec=logging.Logger)
    manager = _make_manager(
        event_logging_enabled=False,
        logger=logger,
        k6_logger=k6_logger,
    )
    old_jsonl = Mock(spec=logging.Handler)
    old_k6_jsonl = Mock(spec=logging.Handler)
    old_loki = Mock(spec=logging.Handler)
    old_k6_loki = Mock(spec=logging.Handler)
    manager._jsonl_handler = old_jsonl
    manager._k6_jsonl_handler = old_k6_jsonl
    manager._loki_handler = old_loki
    manager._k6_loki_handler = old_k6_loki

    jsonl_handlers = [Mock(spec=logging.Handler), Mock(spec=logging.Handler)]
    loki_handlers = [Mock(spec=logging.Handler), Mock(spec=logging.Handler)]

    def attach_jsonl(*_args, **_kwargs):
        return jsonl_handlers.pop(0)

    def attach_loki(*_args, **_kwargs):
        return loki_handlers.pop(0)

    monkeypatch.setattr(log_manager_mod, "attach_jsonl_handler", attach_jsonl)
    monkeypatch.setattr(log_manager_mod, "attach_loki_handler", attach_loki)
    monkeypatch.setattr(
        log_manager_mod,
        "JsonlLogFormatter",
        lambda **_kwargs: logging.Formatter("%(message)s"),
    )

    output_dir = tmp_path / "logs"
    manager.attach_handlers(output_dir, "run-99")

    assert output_dir.exists()
    assert manager._event_run_id == "run-99"
    logger.removeHandler.assert_any_call(old_jsonl)
    logger.removeHandler.assert_any_call(old_loki)
    k6_logger.removeHandler.assert_any_call(old_k6_jsonl)
    k6_logger.removeHandler.assert_any_call(old_k6_loki)
    old_jsonl.close.assert_called_once()
    old_k6_jsonl.close.assert_called_once()
    old_loki.close.assert_called_once()
    old_k6_loki.close.assert_called_once()
    manager._loki_handler.setFormatter.assert_called_once()
    manager._k6_loki_handler.setFormatter.assert_called_once()


def test_emit_log_emits_lb_event_when_enabled() -> None:
    event_emitter = Mock()
    manager = _make_manager(event_logging_enabled=True, event_emitter=event_emitter)
    manager.set_run_id("run-1")

    manager.emit_log("hello", level="WARNING")

    event_emitter.emit.assert_called_once()
    emitted = event_emitter.emit.call_args.args[0]
    assert emitted.run_id == "run-1"
    assert emitted.workload == "peva_faas"
    assert emitted.level == "WARNING"
    manager.logger.log.assert_not_called()


def test_emit_log_falls_back_to_logger_without_run_id() -> None:
    manager = _make_manager(event_logging_enabled=True)

    manager.emit_log("fallback")

    manager.event_emitter.emit.assert_not_called()
    manager.logger.log.assert_called_once()


def test_emit_k6_log_falls_back_when_event_logging_disabled() -> None:
    manager = _make_manager(event_logging_enabled=False)

    manager.emit_k6_log("k6 message", level="ERROR")

    manager.event_emitter.emit.assert_not_called()
    manager.k6_logger.log.assert_called_once()


def test_emit_log_skips_lb_event_when_root_handler_present() -> None:
    manager = _make_manager(event_logging_enabled=True)
    manager.set_run_id("run-2")

    root_logger = logging.getLogger()
    lb_handler = LBEventLogHandler(
        run_id="run-2",
        host="node-1",
        workload="peva_faas",
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


def test_log_to_logger_uses_info_level_for_unknown_name() -> None:
    logger = Mock(spec=logging.Logger)

    DfaasLogManager._log_to_logger(logger, "message", "NOT_A_LEVEL")

    logger.log.assert_called_once_with(logging.INFO, "%s", "message")


def test_close_handler_ignores_close_exceptions() -> None:
    handler = Mock(spec=logging.Handler)
    handler.close.side_effect = RuntimeError("boom")

    DfaasLogManager._close_handler(handler)
