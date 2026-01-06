"""Shared logging handlers for structured output."""

from .jsonl_handler import (
    DEFAULT_JSONL_TEMPLATE,
    JsonlLogFormatter,
    JsonlLogHandler,
    resolve_jsonl_path,
)
from .loki_handler import (
    LokiLogEntry,
    LokiPushHandler,
    build_loki_payload,
    normalize_loki_endpoint,
)

__all__ = [
    "DEFAULT_JSONL_TEMPLATE",
    "JsonlLogFormatter",
    "JsonlLogHandler",
    "resolve_jsonl_path",
    "LokiLogEntry",
    "LokiPushHandler",
    "build_loki_payload",
    "normalize_loki_endpoint",
]
