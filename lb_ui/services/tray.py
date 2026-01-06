"""System tray service for benchmark monitoring."""

from __future__ import annotations

import logging
import multiprocessing
import os
from pathlib import Path
from typing import Optional

try:
    from PIL import Image
    import pystray
except ImportError:
    Image = None
    pystray = None

logger = logging.getLogger(__name__)


def _resolve_icon_path() -> Path | None:
    """Resolve the path to the application icon."""
    try:
        # Reusing the logic from notifier.py
        current_file = Path(__file__)
        project_root = current_file.parents[2]
        icon_path = project_root / "docs" / "img" / "lb_mark.png"
        if icon_path.exists():
            return icon_path.absolute()
    except Exception:
        pass
    return None


def _get_cache_dir() -> Path:
    """Get or create the user cache directory for LB."""
    # Use standard XDG_CACHE_HOME or fallback to ~/.cache
    cache_base = os.environ.get("XDG_CACHE_HOME")
    if cache_base:
        path = Path(cache_base) / "lb"
    else:
        path = Path.home() / ".cache" / "lb"
    
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception:
        # Fallback to system temp if home is not writable
        import tempfile
        path = Path(tempfile.gettempdir()) / "lb_cache"
        path.mkdir(parents=True, exist_ok=True)
    return path


def _resolve_icon_paths() -> tuple[Path | None, Path]:
    """Resolve the source icon path and the target cache path."""
    source_path = None
    try:
        current_file = Path(__file__)
        project_root = current_file.parents[2]
        maybe_source = project_root / "docs" / "img" / "lb_mark.png"
        if maybe_source.exists():
            source_path = maybe_source.absolute()
    except Exception:
        pass
    
    # Using 128x128 for better high-DPI support
    cache_path = _get_cache_dir() / "tray_icon_128.png"
    return source_path, cache_path


def _run_tray_icon(stop_event: multiprocessing.Event) -> None:
    """The entry point for the tray icon process."""
    if pystray is None or Image is None:
        return

    source_path, cache_path = _resolve_icon_paths()
    
    try:
        # Try to load from cache first
        if cache_path.exists():
            final_image = Image.open(cache_path)
        elif source_path:
            # Generate and cache
            source_image = Image.open(source_path)
            if source_image.mode != "RGBA":
                source_image = source_image.convert("RGBA")

            # CROP: Remove empty transparent space around the logo
            # This is crucial to make the icon appear larger in the tray
            bbox = source_image.getbbox()
            if bbox:
                source_image = source_image.crop(bbox)

            target_size = (128, 128)
            width, height = source_image.size
            aspect = width / height
            
            if aspect > 1:
                # Wider than tall
                new_width = target_size[0]
                new_height = int(target_size[0] / aspect)
            else:
                # Taller than wide
                new_height = target_size[1]
                new_width = int(target_size[1] * aspect)
                
            resized_img = source_image.resize(
                (new_width, new_height), 
                resample=Image.Resampling.LANCZOS
            )
            
            final_image = Image.new("RGBA", target_size, (0, 0, 0, 0))
            offset = (
                (target_size[0] - new_width) // 2,
                (target_size[1] - new_height) // 2
            )
            final_image.paste(resized_img, offset)
            
            # Save to cache for next time
            final_image.save(cache_path, "PNG")
        else:
            return

        # Define a simple menu
        menu = pystray.Menu(
            pystray.MenuItem("Linux Benchmark Lib", lambda: None, enabled=False),
            pystray.MenuItem("Benchmark in corso...", lambda: None, enabled=False),
        )

        icon = pystray.Icon(
            "lb_runner",
            final_image,
            title="Linux Benchmark Lib",
            menu=menu
        )

        icon.run()
    except Exception:
        # Silently fail in headless or problematic environments
        pass


class TrayManager:
    """Manages the lifecycle of the system tray icon process."""

    def __init__(self) -> None:
        self._process: Optional[multiprocessing.Process] = None
        self._stop_event = multiprocessing.get_context("spawn").Event()

    def start(self) -> None:
        """Start the tray icon in a separate process."""
        if pystray is None:
            return

        # We use 'spawn' context for better cross-platform consistency, 
        # especially on macOS.
        ctx = multiprocessing.get_context("spawn")
        self._process = ctx.Process(
            target=_run_tray_icon,
            args=(self._stop_event,),
            daemon=True
        )
        try:
            self._process.start()
        except Exception as exc:
            logger.debug(f"Failed to start tray icon process: {exc}")

    def stop(self) -> None:
        """Stop the tray icon process."""
        if self._process and self._process.is_alive():
            self._process.terminate()
            self._process.join(timeout=1)
            if self._process.is_alive():
                self._process.kill()
        self._process = None
