"""Public API surface for lb_common."""

from lb_common.hosts import RemoteHostSpec
from lb_common.logging import configure_logging
from lb_common.logs.core import attach_jsonl_handler, attach_loki_handler
from lb_common.logs.handlers.jsonl_handler import JsonlLogFormatter
from lb_common.run_info import RunInfo


def parse_bool_env(value: str | None) -> bool | None:
    """Parse a boolean env value, returning None when unset or invalid."""
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


def parse_int_env(value: str | None) -> int | None:
    """Parse an integer env value, returning None when unset or invalid."""
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    try:
        return int(normalized)
    except (TypeError, ValueError):
        return None


__all__ = [
    "configure_logging",
    "attach_jsonl_handler",
    "attach_loki_handler",
    "JsonlLogFormatter",
    "parse_bool_env",
    "parse_int_env",
    "RemoteHostSpec",
    "RunInfo",
]
