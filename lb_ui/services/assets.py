"""Shared asset and cache management for UI components."""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    Image = None

logger = logging.getLogger(__name__)


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


def _calculate_file_hash(path: Path) -> str:
    """Calculate MD5 hash of a file."""
    hash_md5 = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()[:8]  # Short hash is enough


def _generate_optimized_icon(source: Path, dest: Path) -> None:
    """Generate a high-quality, cropped, resized icon."""
    if Image is None:
        return

    try:
        img = Image.open(source)
        if img.mode != "RGBA":
            img = img.convert("RGBA")

        # Crop transparent borders
        alpha = img.getchannel("A")
        mask = alpha.point(lambda p: 255 if p > 10 else 0)
        bbox = mask.getbbox()
        if bbox:
            img = img.crop(bbox)

        # Resize to 64x64 (High-DPI tray standard)
        target_h = 64
        width, height = img.size
        ratio = target_h / height
        new_size = (int(width * ratio), target_h)

        resized = img.resize(new_size, resample=Image.Resampling.LANCZOS)
        resized.save(dest, "PNG")
    except Exception as exc:
        logger.debug(f"Failed to generate icon: {exc}")


def _cleanup_old_icons(cache_dir: Path, current_hash: str) -> None:
    """Remove icons from previous versions."""
    for file in cache_dir.glob("icon_*_64.png"):
        if current_hash not in file.name:
            try:
                file.unlink()
            except OSError:
                pass


def resolve_icon_path() -> str | None:
    """Resolve and ensure the optimized icon exists in cache.

    Returns the absolute path to the optimized icon (or source fallback).
    """
    try:
        # 1. Find source
        current_file = Path(__file__)
        project_root = current_file.parents[2]
        source_path = None
        for logo_name in ["logo_sys2.png", "logo_sys.png", "lb_mark.png"]:
            candidate = project_root / "docs" / "img" / logo_name
            if candidate.exists():
                source_path = candidate
                break

        if not source_path:
            return None

        # 2. Check cache based on source content hash
        file_hash = _calculate_file_hash(source_path)
        cache_dir = get_cache_dir()
        cached_icon = cache_dir / f"icon_{file_hash}_64.png"

        if cached_icon.exists():
            return str(cached_icon.absolute())

        # 3. Generate if missing
        _generate_optimized_icon(source_path, cached_icon)

        # 4. Cleanup old versions
        _cleanup_old_icons(cache_dir, file_hash)

        if cached_icon.exists():
            return str(cached_icon.absolute())

        # Fallback to source if generation failed
        return str(source_path.absolute())

    except Exception as exc:
        logger.debug(f"Icon resolution failed: {exc}")
        return None
