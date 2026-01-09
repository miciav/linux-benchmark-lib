"""Loki environment fallback helpers."""

from __future__ import annotations

import os
from typing import Any, MutableMapping

from lb_common.api import (
    parse_bool_env,
    parse_float_env,
    parse_int_env,
    parse_labels_env,
)


def apply_loki_env_fallbacks(values: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    _fallback_bool(values, "enabled", "LB_LOKI_ENABLED")
    _fallback_str(values, "endpoint", "LB_LOKI_ENDPOINT")
    _merge_labels(values, "LB_LOKI_LABELS")
    _fallback_int(values, "batch_size", "LB_LOKI_BATCH_SIZE")
    _fallback_int(values, "flush_interval_ms", "LB_LOKI_FLUSH_INTERVAL_MS")
    _fallback_float(values, "timeout_seconds", "LB_LOKI_TIMEOUT_SECONDS")
    _fallback_int(values, "max_retries", "LB_LOKI_MAX_RETRIES")
    _fallback_int(values, "max_queue_size", "LB_LOKI_MAX_QUEUE_SIZE")
    _fallback_float(values, "backoff_base", "LB_LOKI_BACKOFF_BASE")
    _fallback_float(values, "backoff_factor", "LB_LOKI_BACKOFF_FACTOR")
    return values


def _fallback_bool(values: MutableMapping[str, Any], key: str, env_var: str) -> None:
    if values.get(key) is None:
        env_value = parse_bool_env(os.environ.get(env_var))
        if env_value is not None:
            values[key] = env_value


def _fallback_str(values: MutableMapping[str, Any], key: str, env_var: str) -> None:
    if not values.get(key):
        env_value = os.environ.get(env_var)
        if env_value:
            values[key] = env_value


def _fallback_int(values: MutableMapping[str, Any], key: str, env_var: str) -> None:
    if values.get(key) is None:
        env_value = parse_int_env(os.environ.get(env_var))
        if env_value is not None:
            values[key] = env_value


def _fallback_float(values: MutableMapping[str, Any], key: str, env_var: str) -> None:
    if values.get(key) is None:
        env_value = parse_float_env(os.environ.get(env_var))
        if env_value is not None:
            values[key] = env_value


def _merge_labels(values: MutableMapping[str, Any], env_var: str) -> None:
    env_labels = parse_labels_env(os.environ.get(env_var))
    if not env_labels:
        return
    merged = dict(env_labels)
    merged.update(values.get("labels") or {})
    values["labels"] = merged
