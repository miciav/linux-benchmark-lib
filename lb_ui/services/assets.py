"""Shared asset and cache management for UI components."""

from __future__ import annotations

import os
from pathlib import Path

def get_cache_dir() -> Path:
    """Get the user cache directory for LB."""
    cache_base = os.environ.get("XDG_CACHE_HOME")
    if cache_base:
        path = Path(cache_base) / "lb"
    else:
        path = Path.home() / ".cache" / "lb"
    
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception:
        import tempfile
        path = Path(tempfile.gettempdir()) / "lb_cache"
        path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_icon_path(variant: str = "v7_64") -> str | None:
    """Resolve the path to the best available application icon.
    
    Args:
        variant: The preferred cached variant name (e.g. 'v7_64')
    """
    try:
        # 1. Try preferred cached version
        cache_icon = get_cache_dir() / f"tray_icon_{variant}.png"
        if cache_icon.exists():
            return str(cache_icon.absolute())

        # 2. Fallback to any cached version
        for old_path in get_cache_dir().glob("tray_icon_*.png"):
            return str(old_path.absolute())

        # 3. Fallback to source
        current_file = Path(__file__)
        # lb_ui/services/assets.py -> project_root/docs/img/logo_sys2.png
        project_root = current_file.parents[2]
        for logo_name in ["logo_sys2.png", "logo_sys.png", "lb_mark.png"]:
            source_icon = project_root / "docs" / "img" / logo_name
            if source_icon.exists():
                return str(source_icon.absolute())
    except Exception:
        pass
    return None
