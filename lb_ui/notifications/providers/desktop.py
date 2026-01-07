"""Desktop notification provider with cross-platform support."""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import subprocess
import time
from typing import Optional

from lb_ui.notifications.base import NotificationProvider, NotificationContext

# Optional dependencies
try:
    from plyer import notification
except ImportError:
    notification = None

try:
    from desktop_notifier import DesktopNotifier
except ImportError:
    DesktopNotifier = None

logger = logging.getLogger(__name__)


class DesktopProvider(NotificationProvider):
    """Handles local desktop notifications for macOS and Linux."""

    def __init__(self, app_name: str):
        self.app_name = app_name

    def send(self, context: NotificationContext) -> None:
        if self._is_headless():
            logger.debug("Headless environment detected; skipping desktop notification")
            return

        self._play_sound()

        system = platform.system()
        if system == "Darwin":
            self._send_macos(context)
        elif system == "Linux":
            self._send_linux(context)

    def _is_headless(self) -> bool:
        """Check if we are running without a GUI."""
        if platform.system() == "Linux":
            return not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
        return False

    def _play_sound(self) -> None:
        """Play system notification sound (best effort)."""
        try:
            if platform.system() == "Linux":
                subprocess.Popen(
                    ["canberra-gtk-play", "--id=message-new-instant"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
        except Exception:
            pass

    def _send_linux(self, context: NotificationContext) -> None:
        """Send notification using plyer on Linux."""
        if notification is None:
            logger.debug("plyer not installed, skipping Linux notification")
            return
            
        try:
            notification.notify(
                title=context.title,
                message=context.message,
                app_name=self.app_name,
                app_icon=context.icon_path,
                timeout=10
            )
        except Exception as exc:
            logger.warning(f"Linux notification failed: {exc}")

    def _send_macos(self, context: NotificationContext) -> None:
        """Send notification using desktop-notifier or osascript fallback."""
        # Try modern API first
        if DesktopNotifier is not None:
            try:
                notifier = DesktopNotifier(
                    app_name=self.app_name, 
                    app_icon=context.icon_path
                )
                asyncio.run(notifier.send(
                    title=context.title,
                    message=context.message,
                    icon=context.icon_path
                ))
                # Grace period for asset loading
                time.sleep(3)
                return
            except Exception as exc:
                logger.debug(f"desktop-notifier failed, trying fallback: {exc}")

        # Fallback
        self._send_macos_osascript(context)
        time.sleep(3)

    def _send_macos_osascript(self, context: NotificationContext) -> None:
        """Execute AppleScript via osascript."""
        # Basic escaping to prevent syntax errors
        safe_title = context.title.replace('"', '\"')
        safe_message = context.message.replace('"', '\"')
        
        script = (
            f'display notification "{safe_message}" '
            f'with title "{safe_title}" '
            'sound name "Glass"'
        )
        
        if context.icon_path:
            script += f' with icon file (POSIX file "{context.icon_path}")'
            
        try:
            subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                timeout=5
            )
        except Exception as exc:
            logger.warning(f"macOS fallback notification failed: {exc}")