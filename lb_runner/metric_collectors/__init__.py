"""Metric collectors package for Linux performance benchmarking.

Collectors are exposed lazily to avoid importing optional dependencies at
module import time.
"""

from __future__ import annotations

import importlib
from typing import Any

__all__ = ["CLICollector", "PSUtilCollector"]

_LAZY_MODULES: dict[str, str] = {
    "PSUtilCollector": "psutil_collector",
    "CLICollector": "cli_collector",
}


def __getattr__(name: str) -> Any:
    if name in _LAZY_MODULES:
        module = importlib.import_module(f"{__name__}.{_LAZY_MODULES[name]}")
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
