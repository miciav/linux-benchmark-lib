"""Default cartesian scheduler for PEVA-faas configurations."""

from __future__ import annotations

from .contracts import ConfigKey, ConfigPairs
from .plan_builder import config_key


class CartesianScheduler:
    """Return configs in deterministic cartesian order with seen-key filtering."""

    def propose_batch(
        self,
        *,
        candidates: list[ConfigPairs],
        seen_keys: set[ConfigKey],
        desired_size: int,
    ) -> list[ConfigPairs]:
        if desired_size <= 0:
            return []
        selected: list[ConfigPairs] = []
        for config_pairs in candidates:
            if len(selected) >= desired_size:
                break
            if config_key(config_pairs) in seen_keys:
                continue
            selected.append(config_pairs)
        return selected
