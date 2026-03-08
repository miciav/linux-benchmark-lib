from __future__ import annotations

import importlib
import sys
from typing import Any

_fuzz: Any | None = None
_process: Any | None = None

try:
    _fuzz = importlib.import_module("rapidfuzz.fuzz")
    _process = importlib.import_module("rapidfuzz.process")
    _HAS_RAPIDFUZZ = True
except Exception:  # pragma: no cover - optional dependency
    _HAS_RAPIDFUZZ = False


def is_tty_available() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def supports_fullscreen_ui() -> bool:
    return is_tty_available()


def has_fuzzy_search() -> bool:
    return _HAS_RAPIDFUZZ


def fuzzy_matcher() -> tuple[Any, Any] | None:
    if not _HAS_RAPIDFUZZ or _process is None or _fuzz is None:
        return None
    return _process, _fuzz.WRatio
