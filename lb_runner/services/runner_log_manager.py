"""Logging helpers for local benchmark runs."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from lb_common.api import JsonlLogFormatter, attach_jsonl_handler, attach_loki_handler
from lb_runner.models.config import BenchmarkConfig


class _ExcludeLoggerPrefixFilter(logging.Filter):
    def __init__(self, prefixes: tuple[str, ...]) -> None:
        super().__init__()
        self._prefixes = prefixes

    def filter(self, record: logging.LogRecord) -> bool:
        return not any(record.name.startswith(prefix) for prefix in self._prefixes)


@dataclass
class RunnerLogManager:
    """Manage JSONL/Loki log handlers for local runs."""

    config: BenchmarkConfig
    host_name: str
    logger: logging.Logger

    _jsonl_handler: logging.Handler | None = None
    _loki_handler: logging.Handler | None = None

    def attach(
        self,
        *,
        output_dir: Path,
        run_id: str,
        workload: str | None = None,
        repetition: int | None = None,
        phase: str | None = None,
    ) -> None:
        root_logger = logging.getLogger()
        if self._jsonl_handler:
            root_logger.removeHandler(self._jsonl_handler)
            try:
                self._jsonl_handler.close()
            except Exception:
                pass
        tags = {"phase": phase} if phase else None
        self._jsonl_handler = attach_jsonl_handler(
            root_logger,
            output_dir=output_dir,
            component="runner",
            host=self.host_name,
            run_id=run_id,
            workload=workload,
            package="lb_runner",
            repetition=repetition,
            tags=tags,
        )
        if self._jsonl_handler:
            self._jsonl_handler.addFilter(_ExcludeLoggerPrefixFilter(("lb_plugins.",)))
        self._attach_loki(
            run_id,
            workload=workload,
            repetition=repetition,
            phase=phase,
        )

    def _attach_loki(
        self,
        run_id: str,
        *,
        workload: str | None = None,
        repetition: int | None = None,
        phase: str | None = None,
    ) -> None:
        root_logger = logging.getLogger()
        if self._loki_handler:
            root_logger.removeHandler(self._loki_handler)
            try:
                self._loki_handler.close()
            except Exception:
                pass
            self._loki_handler = None

        loki_cfg = self.config.loki
        labels = dict(loki_cfg.labels)
        if phase:
            labels.setdefault("phase", phase)
        self._loki_handler = attach_loki_handler(
            root_logger,
            enabled=loki_cfg.enabled,
            endpoint=loki_cfg.endpoint,
            component="runner",
            host=self.host_name,
            run_id=run_id,
            workload=workload,
            package="lb_runner",
            repetition=repetition,
            labels=labels,
            batch_size=loki_cfg.batch_size,
            flush_interval_ms=loki_cfg.flush_interval_ms,
            timeout_seconds=loki_cfg.timeout_seconds,
            max_retries=loki_cfg.max_retries,
            max_queue_size=loki_cfg.max_queue_size,
            backoff_base=loki_cfg.backoff_base,
            backoff_factor=loki_cfg.backoff_factor,
        )
        if self._loki_handler:
            self._loki_handler.setFormatter(
                JsonlLogFormatter(
                    component="runner",
                    host=self.host_name,
                    run_id=run_id,
                    workload=workload,
                    package="lb_runner",
                    repetition=repetition,
                    tags={"phase": phase} if phase else None,
                )
            )
            self._loki_handler.addFilter(_ExcludeLoggerPrefixFilter(("lb_plugins.",)))

    def sync_loki_env(self) -> None:
        if not self.config.loki.enabled:
            return
        loki_cfg = self.config.loki
        os.environ.setdefault("LB_LOKI_ENABLED", "1")
        os.environ.setdefault("LB_LOKI_ENDPOINT", loki_cfg.endpoint)
        if loki_cfg.labels:
            labels = ",".join(
                f"{key}={value}"
                for key, value in loki_cfg.labels.items()
                if value is not None
            )
            if labels:
                os.environ.setdefault("LB_LOKI_LABELS", labels)
        os.environ.setdefault("LB_LOKI_BATCH_SIZE", str(loki_cfg.batch_size))
        os.environ.setdefault(
            "LB_LOKI_FLUSH_INTERVAL_MS", str(loki_cfg.flush_interval_ms)
        )
        os.environ.setdefault("LB_LOKI_TIMEOUT_SECONDS", str(loki_cfg.timeout_seconds))
        os.environ.setdefault("LB_LOKI_MAX_RETRIES", str(loki_cfg.max_retries))
