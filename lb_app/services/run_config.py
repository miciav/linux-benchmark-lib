"""Config hashing helpers for run orchestration."""

from __future__ import annotations

import hashlib
import json

from lb_controller.api import BenchmarkConfig


def hash_config(cfg: BenchmarkConfig | None) -> str:
    """Return a stable hash for a BenchmarkConfig."""
    if cfg is None:
        return ""
    try:
        dump = cfg.model_dump(mode="json")
        return hashlib.sha256(
            json.dumps(dump, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
    except Exception:
        try:
            return hashlib.sha256(str(cfg).encode("utf-8")).hexdigest()
        except Exception:
            return ""
