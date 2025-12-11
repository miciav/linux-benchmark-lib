"""Bridge to construct DataHandler lazily without hard dependency at import time."""

from __future__ import annotations

from typing import Any, Dict


def make_data_handler(collectors: Dict[str, Any]):
    """Instantiate the analytics DataHandler lazily to avoid import cycles."""
    from lb_analytics.aggregators.data_handler import DataHandler as Handler  # type: ignore

    return Handler(collectors=collectors)
