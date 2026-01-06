"""System notification service for benchmark completion events."""

from __future__ import annotations

import logging
import platform
import subprocess
import os
from pathlib import Path
from typing import Optional

try:
    from plyer import notification
except ImportError:
    notification = None  # Handle environments where plyer might not be installed

logger = logging.getLogger(__name__)


def _get_cache_dir() -> Path:
    """Get the user cache directory for LB (consistent with tray.py)."""
    cache_base = os.environ.get("XDG_CACHE_HOME")
    if cache_base:
        path = Path(cache_base) / "lb"
    else:
        path = Path.home() / ".cache" / "lb"
    return path


def _resolve_icon_path() -> str | None:
    """Resolve the path to the best available application icon."""
    try:
        # Priority 1: Optimized cached icon (cropped and high-res)
        cache_icon = _get_cache_dir() / "tray_icon_128.png"
        if cache_icon.exists():
            return str(cache_icon.absolute())

        # Priority 2: Original source icon
        current_file = Path(__file__)
        project_root = current_file.parents[2]
        source_icon = project_root / "docs" / "img" / "lb_mark.png"
        if source_icon.exists():
            return str(source_icon.absolute())
    except Exception:
        pass
    return None


def _send_macos_notification(title: str, message: str, icon_path: str | None = None) -> None:
    """Send notification on macOS using osascript with optional icon support."""
    # Simple escaping for AppleScript double quotes
    safe_title = title.replace('"', '\\"')
    safe_message = message.replace('"', '\\"')
    
    script = f'display notification "{safe_message}" with title "{safe_title}"'
    if icon_path:
        # Note: 'with icon file' requires a POSIX file path in AppleScript
        script += f' with icon file (POSIX file "{icon_path}")'

    subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        check=True,
        timeout=5,
    )


def send_notification(
    title: str,
    message: str,
    success: bool = True,
    app_name: str = "Linux Benchmark Lib",
    timeout: int = 10,
) -> None:
    """Send a desktop notification with icon support.

    Args:
        title: Notification title
        message: Notification body
        success: Whether the operation was successful
        app_name: Name of the application sending the notification
        timeout: Duration in seconds to show the notification
    """
    try:
        icon_path = _resolve_icon_path()

        if platform.system() == "Darwin":
            _send_macos_notification(title, message, icon_path)
            return

        if notification is None:
            logger.debug("plyer not installed; skipping notification")
            return

        # On some platforms/environments (like headless CI), notification.notify might raise an error
        # or just fail silently. We wrap it to ensure it doesn't crash the main app.
        notification.notify(
            title=title,
            message=message,
            app_name=app_name,
            timeout=timeout,
            app_icon=icon_path,
        )
    except Exception as exc:
        logger.warning(f"Failed to send system notification: {exc}")
