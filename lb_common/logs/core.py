"""Shared logging configuration using structlog."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional, Mapping, Any

import structlog

from lb_common.config.env import (
    parse_bool_env,
    parse_float_env,
    parse_int_env,
    parse_labels_env,
)
from lb_common.logs.handlers.jsonl_handler import (
    DEFAULT_JSONL_TEMPLATE,
    JsonlLogHandler,
)
from lb_common.logs.handlers.loki_handler import LokiPushHandler


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


def build_jsonl_handler(
    *,
    output_dir: Path | str,
    component: str,
    host: str,
    run_id: str,
    path_template: str | None = None,
    event_type: str = "log",
    workload: str | None = None,
    package: str | None = None,
    plugin: str | None = None,
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
        resolved_max_bytes = parse_int_env(os.environ.get("LB_JSONL_LOG_ROTATE_BYTES"))
    resolved_backup_count = backup_count
    if resolved_backup_count is None:
        resolved_backup_count = parse_int_env(os.environ.get("LB_JSONL_LOG_BACKUPS"))
    return JsonlLogHandler(
        output_dir=output_dir,
        component=component,
        host=host,
        run_id=run_id,
        path_template=resolved_template,
        event_type=event_type,
        workload=workload,
        package=package,
        plugin=plugin,
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
    package: str | None = None,
    plugin: str | None = None,
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
    """Create a Loki handler.

    Priority: explicit parameters > environment variables > defaults.
    Environment variables are only used as fallbacks when parameters are None.
    """
    resolved_enabled = _resolve_loki_enabled(enabled)
    if not resolved_enabled:
        return None

    resolved_endpoint = _resolve_loki_endpoint(endpoint)
    resolved_labels = _resolve_loki_labels(labels)
    resolved_batch_size = _resolve_env_value(
        batch_size, "LB_LOKI_BATCH_SIZE", parse_int_env
    )
    resolved_flush_ms = _resolve_env_value(
        flush_interval_ms, "LB_LOKI_FLUSH_INTERVAL_MS", parse_int_env
    )
    resolved_timeout = _resolve_env_value(
        timeout_seconds, "LB_LOKI_TIMEOUT_SECONDS", parse_float_env
    )
    resolved_max_retries = _resolve_env_value(
        max_retries, "LB_LOKI_MAX_RETRIES", parse_int_env
    )
    resolved_queue_size = _resolve_env_value(
        max_queue_size, "LB_LOKI_MAX_QUEUE_SIZE", parse_int_env
    )
    resolved_backoff_base = _resolve_env_value(
        backoff_base, "LB_LOKI_BACKOFF_BASE", parse_float_env
    )
    resolved_backoff_factor = _resolve_env_value(
        backoff_factor, "LB_LOKI_BACKOFF_FACTOR", parse_float_env
    )

    resolved_batch_size = _coalesce(resolved_batch_size, 100)
    resolved_flush_ms = _coalesce(resolved_flush_ms, 1000)
    resolved_timeout = _coalesce(resolved_timeout, 5.0)
    resolved_max_retries = _coalesce(resolved_max_retries, 3)
    resolved_queue_size = _coalesce(resolved_queue_size, 10000)
    resolved_backoff_base = _coalesce(resolved_backoff_base, 0.5)
    resolved_backoff_factor = _coalesce(resolved_backoff_factor, 2.0)

    return LokiPushHandler(
        endpoint=resolved_endpoint,
        component=component,
        host=host,
        run_id=run_id,
        workload=workload,
        package=package,
        plugin=plugin,
        scenario=scenario,
        repetition=repetition,
        labels=resolved_labels,
        batch_size=resolved_batch_size,
        flush_interval=resolved_flush_ms / 1000.0,
        timeout_seconds=resolved_timeout,
        max_retries=resolved_max_retries,
        max_queue_size=resolved_queue_size,
        backoff_base=resolved_backoff_base,
        backoff_factor=resolved_backoff_factor,
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
    package: str | None = None,
    plugin: str | None = None,
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
        package=package,
        plugin=plugin,
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
    package: str | None = None,
    plugin: str | None = None,
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
        package=package,
        plugin=plugin,
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
    env_level, env_json, env_log_file = _read_logging_env()
    resolved_level = _resolve_level(level or env_level, debug)
    resolved_json = env_json if json is None else json
    resolved_log_file = env_log_file if log_file is None else log_file

    formatter = _make_structlog_formatter(resolved_json)
    root_logger = logging.getLogger()
    if _reuse_existing_handlers(root_logger, force):
        _configure_structlog()
        return

    handlers = _build_handlers(
        formatter, resolved_log_file, jsonl_handler, loki_handler
    )
    if force:
        root_logger.handlers.clear()

    _attach_handlers(root_logger, resolved_level, handlers)
    _configure_structlog()


def _resolve_loki_enabled(enabled: bool | None) -> bool:
    env_enabled = parse_bool_env(os.environ.get("LB_LOKI_ENABLED"))
    if enabled is not None:
        return enabled
    return env_enabled if env_enabled is not None else False


def _resolve_loki_endpoint(endpoint: str | None) -> str:
    return endpoint or os.environ.get("LB_LOKI_ENDPOINT") or "http://localhost:3100"


def _resolve_loki_labels(labels: Mapping[str, Any] | None) -> dict[str, Any]:
    env_labels = parse_labels_env(os.environ.get("LB_LOKI_LABELS"))
    resolved_labels = dict(env_labels or {})
    if labels:
        resolved_labels.update(labels)  # Config labels override env labels
    return resolved_labels


def _resolve_env_value(
    value: Any, env_key: str, parser: Any
) -> Any:
    if value is not None:
        return value
    return parser(os.environ.get(env_key))


def _coalesce(value: Any, default: Any) -> Any:
    return default if value is None else value


def _read_logging_env() -> tuple[str | None, bool | None, str | None]:
    return (
        os.environ.get("LB_LOG_LEVEL"),
        parse_bool_env(os.environ.get("LB_LOG_JSON")),
        os.environ.get("LB_LOG_FILE"),
    )


def _make_structlog_formatter(
    resolved_json: bool | None,
) -> structlog.stdlib.ProcessorFormatter:
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

    return structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=pre_chain,
    )


def _reuse_existing_handlers(root_logger: logging.Logger, force: bool) -> bool:
    return bool(root_logger.handlers) and not force


def _build_handlers(
    formatter: structlog.stdlib.ProcessorFormatter,
    log_file: str | None,
    jsonl_handler: logging.Handler | None,
    loki_handler: logging.Handler | None,
) -> list[logging.Handler]:
    handlers: list[logging.Handler] = []
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    handlers.append(stream_handler)
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)
    if jsonl_handler:
        handlers.append(jsonl_handler)
    if loki_handler:
        handlers.append(loki_handler)
    return handlers


def _attach_handlers(
    root_logger: logging.Logger, level: int, handlers: list[logging.Handler]
) -> None:
    root_logger.setLevel(level)
    for handler in handlers:
        root_logger.addHandler(handler)


def _configure_structlog() -> None:
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
