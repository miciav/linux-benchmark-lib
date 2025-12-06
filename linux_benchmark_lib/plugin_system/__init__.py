"""Compatibility shim for plugin_system package.

Extends the module search path to include lb_runner.plugin_system so
legacy imports continue to work.
"""

from __future__ import annotations

import pkgutil
from pathlib import Path

import lb_runner.plugin_system as _ps

# Extend package search path to lb_runner.plugin_system
__path__ = pkgutil.extend_path(__path__, __name__)  # type: ignore[var-annotated]
__path__.append(str(Path(_ps.__file__).parent))

# Re-export common symbols for convenience
from lb_runner.plugin_system import *  # noqa: F401,F403
