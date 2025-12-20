"""Shared logging configuration using structlog."""

from __future__ import annotations

import logging
import os
import sys
from typing import Optional

import structlog


def _resolve_level(value: str | int | None, debug: bool) -> int:
    if debug:
        return logging.DEBUG
    if value is None:
        return logging.INFO
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


def configure_logging(
    *,
    level: str | int | None = None,
    debug: bool = False,
    log_file: str | None = None,
    json: bool | None = None,
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
