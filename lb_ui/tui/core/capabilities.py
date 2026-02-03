from __future__ import annotations

import sys
from typing import Any

try:
    from rapidfuzz import fuzz as _fuzz
    from rapidfuzz import process as _process

    _HAS_RAPIDFUZZ = True
except Exception:  # pragma: no cover - optional dependency
    _fuzz = None
    _process = None
    _HAS_RAPIDFUZZ = False


def is_tty_available() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def supports_fullscreen_ui() -> bool:
    return is_tty_available()


def has_fuzzy_search() -> bool:
    return _HAS_RAPIDFUZZ


def fuzzy_matcher() -> tuple[Any, Any] | None:
    if not _HAS_RAPIDFUZZ:
        return None
    return _process, _fuzz.WRatio
