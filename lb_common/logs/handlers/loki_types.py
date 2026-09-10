"""Shared types for Loki logging helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class LokiLogEntry:
    """Normalized Loki log entry payload."""

    labels: Mapping[str, str]
    timestamp_ns: str
    line: str
