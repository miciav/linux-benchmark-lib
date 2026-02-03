"""Logging utilities for DFaaS execution."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import time
from pathlib import Path

from lb_common.api import JsonlLogFormatter, attach_jsonl_handler, attach_loki_handler
from lb_runner.api import LBEventLogHandler, RunEvent, StdoutEmitter

from ..config import DfaasConfig
from ..context import ExecutionContext


@dataclass
class DfaasLogManager:
    """Attach DFaaS log handlers and emit LB_EVENT logs when enabled."""

    config: DfaasConfig
    exec_ctx: ExecutionContext
    logger: logging.Logger
    k6_logger: logging.Logger = field(
        default_factory=lambda: logging.getLogger(
            "lb_plugins.plugins.dfaas.services.k6_runner"
        )
    )
    event_emitter: StdoutEmitter = field(default_factory=StdoutEmitter)

    _jsonl_handler: logging.Handler | None = None
    _k6_jsonl_handler: logging.Handler | None = None
    _loki_handler: logging.Handler | None = None
    _k6_loki_handler: logging.Handler | None = None
    _event_run_id: str | None = None

    def set_run_id(self, run_id: str) -> None:
        self._event_run_id = run_id

    def attach_handlers(self, output_dir: Path, run_id: str) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        self._event_run_id = run_id

        if self._jsonl_handler:
            self.logger.removeHandler(self._jsonl_handler)
            self._close_handler(self._jsonl_handler)
        self._jsonl_handler = attach_jsonl_handler(
            self.logger,
            output_dir=output_dir,
            component="dfaas",
            host=self.exec_ctx.host,
            run_id=run_id,
            workload="dfaas",
            package="lb_plugins",
            plugin="dfaas",
            repetition=self.exec_ctx.repetition,
        )
        self._attach_loki_handler(run_id)

        if self._k6_jsonl_handler:
            self.k6_logger.removeHandler(self._k6_jsonl_handler)
            self._close_handler(self._k6_jsonl_handler)
        self._k6_jsonl_handler = attach_jsonl_handler(
            self.k6_logger,
            output_dir=output_dir,
            component="k6",
            host=self.exec_ctx.host,
            run_id=run_id,
            workload="dfaas",
            package="lb_plugins",
            plugin="dfaas",
            repetition=self.exec_ctx.repetition,
        )
        self._attach_k6_loki_handler(run_id)

    def emit_log(self, message: str, *, level: str = "INFO") -> None:
        self._emit_event(message, level)

    def emit_k6_log(self, message: str, *, level: str = "INFO") -> None:
        self._emit_event(message, level)

    def _emit_event(self, message: str, level: str) -> None:
        if not self.exec_ctx.event_logging_enabled:
            return
        root_logger = logging.getLogger()
        if any(
            isinstance(handler, LBEventLogHandler)
            for handler in root_logger.handlers
        ):
            return
        if self._event_run_id is None:
            return
        event = RunEvent(
            run_id=self._event_run_id,
            host=self.exec_ctx.host,
            workload="dfaas",
            repetition=self.exec_ctx.repetition,
            total_repetitions=self.exec_ctx.total_repetitions,
            status="running",
            message=message,
            timestamp=time.time(),
            type="log",
            level=level,
        )
        self.event_emitter.emit(event)

    def _attach_loki_handler(self, run_id: str) -> None:
        if self._loki_handler:
            self.logger.removeHandler(self._loki_handler)
            self._close_handler(self._loki_handler)
            self._loki_handler = None
        loki_cfg = self.config.loki
        self._loki_handler = attach_loki_handler(
            self.logger,
            enabled=loki_cfg.enabled,
            endpoint=loki_cfg.endpoint,
            labels=loki_cfg.labels,
            component="dfaas",
            host=self.exec_ctx.host,
            run_id=run_id,
            workload="dfaas",
            package="lb_plugins",
            plugin="dfaas",
            repetition=self.exec_ctx.repetition,
        )
        if self._loki_handler:
            self._loki_handler.setFormatter(
                JsonlLogFormatter(
                    component="dfaas",
                    host=self.exec_ctx.host,
                    run_id=run_id,
                    workload="dfaas",
                    package="lb_plugins",
                    plugin="dfaas",
                    repetition=self.exec_ctx.repetition,
                )
            )

    def _attach_k6_loki_handler(self, run_id: str) -> None:
        if self._k6_loki_handler:
            self.k6_logger.removeHandler(self._k6_loki_handler)
            self._close_handler(self._k6_loki_handler)
            self._k6_loki_handler = None
        loki_cfg = self.config.loki
        self._k6_loki_handler = attach_loki_handler(
            self.k6_logger,
            enabled=loki_cfg.enabled,
            endpoint=loki_cfg.endpoint,
            labels=loki_cfg.labels,
            component="k6",
            host=self.exec_ctx.host,
            run_id=run_id,
            workload="dfaas",
            package="lb_plugins",
            plugin="dfaas",
            repetition=self.exec_ctx.repetition,
        )
        if self._k6_loki_handler:
            self._k6_loki_handler.setFormatter(
                JsonlLogFormatter(
                    component="k6",
                    host=self.exec_ctx.host,
                    run_id=run_id,
                    workload="dfaas",
                    package="lb_plugins",
                    plugin="dfaas",
                    repetition=self.exec_ctx.repetition,
                )
            )

    @staticmethod
    def _close_handler(handler: logging.Handler) -> None:
        try:
            handler.close()
        except Exception:
            pass
