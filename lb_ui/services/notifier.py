import logging
import platform
import os
from pathlib import Path
from typing import Optional

try:
    from plyer import notification
except ImportError:
    notification = None

try:
    from desktop_notifier import DesktopNotifier
except ImportError:
    DesktopNotifier = None

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
        # Priority 1: Optimized cached icon (v4, cropped, 64x64)
        cache_icon = _get_cache_dir() / "tray_icon_v4_64.png"
        if cache_icon.exists():
            return str(cache_icon.absolute())

        # Priority 2: Older cached versions
        for old_name in ["tray_icon_128.png", "tray_icon_64.png"]:
            old_path = _get_cache_dir() / old_name
            if old_path.exists():
                return str(old_path.absolute())
    except Exception:
        pass
    return None


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

        # macOS specific implementation using desktop-notifier (Native API)
        if platform.system() == "Darwin" and DesktopNotifier is not None:
            notifier = DesktopNotifier(app_name=app_name)
            # send_sync is perfect for CLI tools
            notifier.send_sync(
                title=title,
                message=message,
                icon=icon_path,
            )
            return

        # Fallback to plyer for Linux/Windows
        if notification is not None:
            notification.notify(
                title=title,
                message=message,
                app_name=app_name,
                timeout=timeout,
                app_icon=icon_path,
            )
        else:
            logger.debug("No notification implementation available")

    except Exception as exc:
        logger.warning(f"Failed to send system notification: {exc}")
