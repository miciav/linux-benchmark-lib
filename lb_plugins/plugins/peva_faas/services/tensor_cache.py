"""Hot in-memory tensor cache for PEVA-faas execution events."""

from __future__ import annotations

import math

import numpy as np

from .contracts import ConfigKey, ExecutionEvent


class TensorCache:
    """Store numeric event vectors keyed by configuration for fast access."""

    def __init__(self) -> None:
        self._vectors: dict[ConfigKey, np.ndarray] = {}

    def add_event(self, event: ExecutionEvent) -> None:
        """Convert event features into a dense float vector."""
        values: list[float] = []
        for raw in event.result_row.values():
            if isinstance(raw, bool):
                values.append(1.0 if raw else 0.0)
                continue
            if isinstance(raw, (int, float)):
                values.append(float(raw))
                continue
            if isinstance(raw, str):
                try:
                    values.append(float(raw))
                except ValueError:
                    continue
        if not values:
            values = [0.0]
        vector = np.array(values, dtype=float)
        vector = np.nan_to_num(vector, nan=0.0, posinf=math.inf, neginf=-math.inf)
        self._vectors[event.config_key] = vector

    def contains(self, key: ConfigKey) -> bool:
        """Return whether key is present in cache."""
        return key in self._vectors

    def size(self) -> int:
        """Return number of vectors in cache."""
        return len(self._vectors)
