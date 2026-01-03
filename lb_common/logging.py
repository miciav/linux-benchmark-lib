"""Shared logging configuration using structlog."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional, Mapping, Any

import structlog

from lb_common.handlers.jsonl_handler import (
    DEFAULT_JSONL_TEMPLATE,
    JsonlLogHandler,
)
from lb_common.handlers.loki_handler import LokiPushHandler


def _resolve_level(value: str | int | None, debug: bool) -> int:
    if debug:
        return logging.DEBUG
    if value is None:
        return logging.WARNING
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        pass
    return logging._nameToLevel.get(value.upper(), logging.INFO)


def _resolve_bool(value: str | None) -> Optional[bool]:
    if value is None:
        return None
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _resolve_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _resolve_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _resolve_labels(value: str | None) -> dict[str, str]:
    labels: dict[str, str] = {}
    if not value:
        return labels
    for token in value.split(","):
        token = token.strip()
        if not token:
            continue
        if "=" not in token:
            continue
        key, raw_value = token.split("=", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if not key:
            continue
        labels[key] = raw_value
    return labels


def build_jsonl_handler(
    *,
    output_dir: Path | str,
    component: str,
    host: str,
    run_id: str,
    path_template: str | None = None,
    event_type: str = "log",
    workload: str | None = None,
    scenario: str | None = None,
    repetition: int | None = None,
    tags: Mapping[str, Any] | None = None,
    max_bytes: int | None = None,
    backup_count: int | None = None,
) -> JsonlLogHandler:
    """Create a JSONL file handler using defaults and env overrides."""
    resolved_template = (
        path_template
        or os.environ.get("LB_JSONL_LOG_PATH")
        or DEFAULT_JSONL_TEMPLATE
    )
    resolved_max_bytes = max_bytes
    if resolved_max_bytes is None:
        resolved_max_bytes = _resolve_int(os.environ.get("LB_JSONL_LOG_ROTATE_BYTES"))
    resolved_backup_count = backup_count
    if resolved_backup_count is None:
        resolved_backup_count = _resolve_int(os.environ.get("LB_JSONL_LOG_BACKUPS"))
    return JsonlLogHandler(
        output_dir=output_dir,
        component=component,
        host=host,
        run_id=run_id,
        path_template=resolved_template,
        event_type=event_type,
        workload=workload,
        scenario=scenario,
        repetition=repetition,
        tags=tags,
        max_bytes=resolved_max_bytes or 0,
        backup_count=resolved_backup_count or 0,
    )


def build_loki_handler(
    *,
    enabled: bool | None = None,
    endpoint: str | None = None,
    component: str,
    host: str,
    run_id: str,
    workload: str | None = None,
    scenario: str | None = None,
    repetition: int | None = None,
    labels: Mapping[str, Any] | None = None,
    batch_size: int | None = None,
    flush_interval_ms: int | None = None,
    timeout_seconds: float | None = None,
    max_retries: int | None = None,
    max_queue_size: int | None = None,
    backoff_base: float | None = None,
    backoff_factor: float | None = None,
) -> LokiPushHandler | None:
    """Create a Loki handler using defaults and env overrides."""
    env_enabled = _resolve_bool(os.environ.get("LB_LOKI_ENABLED"))
    resolved_enabled = (
        enabled if enabled is not None else (env_enabled if env_enabled is not None else False)
    )
    if not resolved_enabled:
        return None

    resolved_endpoint = endpoint or os.environ.get("LB_LOKI_ENDPOINT") or "http://localhost:3100"
    resolved_labels = dict(labels or {})
    env_labels = _resolve_labels(os.environ.get("LB_LOKI_LABELS"))
    if env_labels:
        resolved_labels.update(env_labels)

    resolved_batch_size = batch_size
    if resolved_batch_size is None:
        resolved_batch_size = _resolve_int(os.environ.get("LB_LOKI_BATCH_SIZE"))
    resolved_flush_ms = flush_interval_ms
    if resolved_flush_ms is None:
        resolved_flush_ms = _resolve_int(os.environ.get("LB_LOKI_FLUSH_INTERVAL_MS"))
    resolved_timeout = timeout_seconds
    if resolved_timeout is None:
        resolved_timeout = _resolve_float(os.environ.get("LB_LOKI_TIMEOUT_SECONDS"))
    resolved_max_retries = max_retries
    if resolved_max_retries is None:
        resolved_max_retries = _resolve_int(os.environ.get("LB_LOKI_MAX_RETRIES"))
    resolved_queue_size = max_queue_size
    if resolved_queue_size is None:
        resolved_queue_size = _resolve_int(os.environ.get("LB_LOKI_MAX_QUEUE_SIZE"))
    resolved_backoff_base = backoff_base
    if resolved_backoff_base is None:
        resolved_backoff_base = _resolve_float(os.environ.get("LB_LOKI_BACKOFF_BASE"))
    resolved_backoff_factor = backoff_factor
    if resolved_backoff_factor is None:
        resolved_backoff_factor = _resolve_float(os.environ.get("LB_LOKI_BACKOFF_FACTOR"))

    return LokiPushHandler(
        endpoint=resolved_endpoint,
        component=component,
        host=host,
        run_id=run_id,
        workload=workload,
        scenario=scenario,
        repetition=repetition,
        labels=resolved_labels,
        batch_size=resolved_batch_size or 100,
        flush_interval=(resolved_flush_ms or 1000) / 1000.0,
        timeout_seconds=resolved_timeout or 5.0,
        max_retries=resolved_max_retries if resolved_max_retries is not None else 3,
        max_queue_size=resolved_queue_size or 10000,
        backoff_base=resolved_backoff_base if resolved_backoff_base is not None else 0.5,
        backoff_factor=resolved_backoff_factor if resolved_backoff_factor is not None else 2.0,
    )


def attach_loki_handler(
    logger: logging.Logger,
    *,
    enabled: bool | None = None,
    endpoint: str | None = None,
    component: str,
    host: str,
    run_id: str,
    workload: str | None = None,
    scenario: str | None = None,
    repetition: int | None = None,
    labels: Mapping[str, Any] | None = None,
    batch_size: int | None = None,
    flush_interval_ms: int | None = None,
    timeout_seconds: float | None = None,
    max_retries: int | None = None,
    max_queue_size: int | None = None,
    backoff_base: float | None = None,
    backoff_factor: float | None = None,
) -> logging.Handler | None:
    """Attach a Loki handler to the provided logger."""
    handler = build_loki_handler(
        enabled=enabled,
        endpoint=endpoint,
        component=component,
        host=host,
        run_id=run_id,
        workload=workload,
        scenario=scenario,
        repetition=repetition,
        labels=labels,
        batch_size=batch_size,
        flush_interval_ms=flush_interval_ms,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        max_queue_size=max_queue_size,
        backoff_base=backoff_base,
        backoff_factor=backoff_factor,
    )
    if handler:
        logger.addHandler(handler)
    return handler


def attach_jsonl_handler(
    logger: logging.Logger,
    *,
    output_dir: Path | str,
    component: str,
    host: str,
    run_id: str,
    path_template: str | None = None,
    event_type: str = "log",
    workload: str | None = None,
    scenario: str | None = None,
    repetition: int | None = None,
    tags: Mapping[str, Any] | None = None,
    max_bytes: int | None = None,
    backup_count: int | None = None,
) -> logging.Handler:
    """Attach a JSONL handler to the provided logger."""
    handler = build_jsonl_handler(
        output_dir=output_dir,
        component=component,
        host=host,
        run_id=run_id,
        path_template=path_template,
        event_type=event_type,
        workload=workload,
        scenario=scenario,
        repetition=repetition,
        tags=tags,
        max_bytes=max_bytes,
        backup_count=backup_count,
    )
    logger.addHandler(handler)
    return handler


def configure_logging(
    *,
    level: str | int | None = None,
    debug: bool = False,
    log_file: str | None = None,
    json: bool | None = None,
    jsonl_handler: logging.Handler | None = None,
    loki_handler: logging.Handler | None = None,
    force: bool = False,
) -> None:
    """Configure stdlib logging and structlog with a shared formatter."""
    env_level = os.environ.get("LB_LOG_LEVEL")
    env_json = _resolve_bool(os.environ.get("LB_LOG_JSON"))
    env_log_file = os.environ.get("LB_LOG_FILE")

    resolved_level = _resolve_level(level or env_level, debug)
    resolved_json = env_json if json is None else json
    resolved_log_file = env_log_file if log_file is None else log_file

    renderer: structlog.types.Processor
    if resolved_json:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    pre_chain = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=pre_chain,
    )

    root_logger = logging.getLogger()
    if root_logger.handlers and not force:
        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.processors.add_log_level,
                structlog.processors.TimeStamper(fmt="iso", utc=True),
                structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
            ],
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )
        return

    handlers: list[logging.Handler] = []
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    handlers.append(stream_handler)

    if resolved_log_file:
        file_handler = logging.FileHandler(resolved_log_file)
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)
    if jsonl_handler:
        handlers.append(jsonl_handler)
    if loki_handler:
        handlers.append(loki_handler)

    if force:
        root_logger.handlers.clear()

    root_logger.setLevel(resolved_level)
    for handler in handlers:
        root_logger.addHandler(handler)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
