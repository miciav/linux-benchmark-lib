"""Icons, stylesheets, and other resources."""

from __future__ import annotations

from importlib import resources
from pathlib import Path


def resource_path(name: str) -> Path:
    """Return a filesystem path for a packaged resource."""
    return Path(resources.files(__name__) / name)


__all__ = ["resource_path"]
