"""Compatibility shim for plugins package.

Extends the module search path to include lb_runner.plugins so legacy
imports (e.g., linux_benchmark_lib.plugins.dd.plugin) continue to work.
"""

from __future__ import annotations

import pkgutil
from pathlib import Path

import lb_runner.plugins as _plugins

__path__ = pkgutil.extend_path(__path__, __name__)  # type: ignore[var-annotated]
__path__.append(str(Path(_plugins.__file__).parent))
