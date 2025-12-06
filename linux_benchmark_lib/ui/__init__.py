"""Compatibility shim for UI package."""

from __future__ import annotations

import pkgutil
from pathlib import Path

import lb_ui.ui as _ui

__path__ = pkgutil.extend_path(__path__, __name__)  # type: ignore[var-annotated]
__path__.append(str(Path(_ui.__file__).parent))
