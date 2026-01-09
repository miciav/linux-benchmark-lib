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

from lb_ui.services.assets import resolve_icon_path

logger = logging.getLogger(__name__)


def _run_tray_icon() -> None:
    """The entry point for the tray icon process."""
    if pystray is None or Image is None:
        return

    icon_path = resolve_icon_path()
    if not icon_path:
        return
    
    try:
        # Load the pre-optimized icon from cache
        final_image = Image.open(icon_path)

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
        pass


class TrayManager:
    """Manages the lifecycle of the system tray icon process."""

    def __init__(self) -> None:
        self._process: Optional[multiprocessing.Process] = None

    def start(self) -> None:
        """Start the tray icon in a separate process."""
        if pystray is None:
            return

        # We use 'spawn' context for better cross-platform consistency, 
        # especially on macOS.
        ctx = multiprocessing.get_context("spawn")
        self._process = ctx.Process(
            target=_run_tray_icon,
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
