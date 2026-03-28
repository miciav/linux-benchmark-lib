"""Tests for controller log handler ownership and cleanup."""

from __future__ import annotations

import logging
from types import SimpleNamespace

from lb_app.services.remote_run_coordinator import ControllerLogHandlers
from lb_app.services.run_execution import AttachedHandler


class _Service:
    def __init__(self) -> None:
        self.controller_logger = logging.getLogger("lb_controller")
        self.root_logger = logging.getLogger()
        self.jsonl_handler = AttachedHandler(
            logger=self.controller_logger,
            handler=logging.NullHandler(),
        )
        self.loki_handler = AttachedHandler(
            logger=self.root_logger,
            handler=logging.NullHandler(),
        )

    def _attach_controller_jsonl(self, *_args, **_kwargs):
        self.controller_logger.addHandler(self.jsonl_handler.handler)
        return self.jsonl_handler

    def _attach_controller_loki(self, *_args, **_kwargs):
        self.root_logger.addHandler(self.loki_handler.handler)
        return self.loki_handler


def test_controller_log_handlers_remove_from_owning_logger() -> None:
    service = _Service()

    with ControllerLogHandlers(service, SimpleNamespace(), SimpleNamespace()):
        assert service.jsonl_handler.handler in service.controller_logger.handlers
        assert service.loki_handler.handler in service.root_logger.handlers

    assert service.jsonl_handler.handler not in service.controller_logger.handlers
    assert service.loki_handler.handler not in service.root_logger.handlers
