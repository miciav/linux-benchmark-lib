"""Compatibility shim for services package."""

from __future__ import annotations

import pkgutil
from pathlib import Path

import lb_controller.services as _services

__path__ = pkgutil.extend_path(__path__, __name__)  # type: ignore[var-annotated]
__path__.append(str(Path(_services.__file__).parent))
