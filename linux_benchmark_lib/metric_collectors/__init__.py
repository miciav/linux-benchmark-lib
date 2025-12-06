"""Compatibility shim for metric_collectors package.

Extends the module search path to include lb_runner.metric_collectors so
legacy imports continue to work.
"""

from __future__ import annotations

import pkgutil
from pathlib import Path

import lb_runner.metric_collectors as _mc

__path__ = pkgutil.extend_path(__path__, __name__)  # type: ignore[var-annotated]
__path__.append(str(Path(_mc.__file__).parent))
