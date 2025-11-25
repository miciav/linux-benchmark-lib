"""
Workload generators package for Linux performance benchmarking.

This package exposes generators lazily to avoid importing heavy optional
dependencies when the package is imported.
"""

from __future__ import annotations

import importlib
from typing import Any, Dict

__all__ = [
    "StressNGGenerator",
    "IPerf3Generator",
    "DDGenerator",
    "FIOGenerator",
    "Top500Generator",
    "GeekbenchGenerator",
    "SysbenchGenerator",
]

_LAZY_MODULES: Dict[str, str] = {
    "StressNGGenerator": "stress_ng_generator",
    "IPerf3Generator": "iperf3_generator",
    "DDGenerator": "dd_generator",
    "FIOGenerator": "fio_generator",
    "Top500Generator": "top500_generator",
    "GeekbenchGenerator": "geekbench_generator",
    "SysbenchGenerator": "sysbench_generator",
}


def __getattr__(name: str) -> Any:
    if name in _LAZY_MODULES:
        module = importlib.import_module(f"{__name__}.{_LAZY_MODULES[name]}")
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
