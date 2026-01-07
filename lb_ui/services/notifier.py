"Notification service with support for Desktop and Webhooks."

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import subprocess
import urllib.request
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

from lb_ui.services.assets import resolve_icon_path

try:
    from plyer import notification
except ImportError:
    notification = None

try:
    from desktop_notifier import DesktopNotifier
except ImportError:
    DesktopNotifier = None

logger = logging.getLogger(__name__)


class NotificationEngine(ABC):
    """Abstract base class for notification delivery engines."""

    @abstractmethod
    def send(self, title: str, message: str, success: bool, icon_path: str | None) -> None:
        """Deliver a notification."""


class DesktopEngine(NotificationEngine):
    """Engine for local desktop notifications."""

    def __init__(self, app_name: str):
        self.app_name = app_name

    def _is_headless(self) -> bool:
        """Check if we are running in a headless environment."""
        if platform.system() == "Linux":
            return not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
        # macOS usually has a GUI session if we are logged in as a user
        return False

    def _send_macos_osascript(self, title: str, message: str, icon_path: str | None) -> None:
        """Fallback for macOS using osascript."""
        safe_title = title.replace('"', '\"')
        safe_message = message.replace('"', '\"')
        script = f'display notification "{safe_message}" with title "{safe_title}" sound name "Glass"'
        if icon_path:
            script += f' with icon file (POSIX file "{icon_path}")'
        try:
            subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
        except Exception as exc:
            logger.debug(f"osascript notification failed: {exc}")

    def _play_sound(self) -> None:
        """Play system notification sound."""
        try:
            if platform.system() == "Darwin":
                subprocess.Popen(["afplay", "/System/Library/Sounds/Note.aiff"], 
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif platform.system() == "Linux":
                subprocess.Popen(["canberra-gtk-play", "--id=message-new-instant"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def send(self, title: str, message: str, success: bool, icon_path: str | None) -> None:
        if self._is_headless():
            logger.debug("Headless environment detected; skipping desktop notification")
            return

        self._play_sound()

        # macOS Path
        if platform.system() == "Darwin":
            if DesktopNotifier is not None:
                try:
                    notifier = DesktopNotifier(app_name=self.app_name, app_icon=icon_path)
                    asyncio.run(notifier.send(title=title, message=message, icon=icon_path))
                    return
                except Exception as exc:
                    logger.debug(f"desktop-notifier failed: {exc}")
            self._send_macos_osascript(title, message, icon_path)
            return

        # Linux/Other Path
        if notification is not None:
            try:
                notification.notify(
                    title=title,
                    message=message,
                    app_name=self.app_name,
                    app_icon=icon_path,
                    timeout=10
                )
            except Exception as exc:
                logger.debug(f"plyer notification failed: {exc}")


class WebhookEngine(NotificationEngine):
    """Engine for remote notifications via webhooks (Slack, Teams, Discord, etc)."""

    def __init__(self, url: str):
        self.url = url

    def send(self, title: str, message: str, success: bool, icon_path: str | None) -> None:
        """Send a POST request with a JSON payload."""
        payload = {
            "text": f"*{title}*\n{message}",
            "title": title,
            "message": message,
            "status": "success" if success else "failed"
        }
        
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                self.url, data=data, headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status >= 400:
                    logger.debug(f"Webhook returned status {resp.status}")
        except Exception as exc:
            logger.debug(f"Webhook delivery failed: {exc}")


def send_notification(
    title: str,
    message: str,
    success: bool = True,
    run_id: str | None = None,
    duration_s: float | None = None,
) -> None:
    """Send notifications across all enabled engines.
    
    The message will be automatically enriched with duration and status if provided.
    """
    app_name = "Linux Benchmark Lib"
    icon_path = resolve_icon_path()
    
    # Enrich message in English as requested
    full_message = message
    if duration_s is not None:
        full_message += f"\nDuration: {duration_s:.1f}s"
    if run_id:
        title = f"Run {run_id}: {title}"

    # Initialize engines
    engines: list[NotificationEngine] = [DesktopEngine(app_name)]
    
    webhook_url = os.environ.get("LB_WEBHOOK_URL")
    if webhook_url:
        engines.append(WebhookEngine(webhook_url))

    # Deliver via all engines
    for engine in engines:
        try:
            engine.send(title, full_message, success, icon_path)
        except Exception as exc:
            logger.warning(f"Notification engine {engine.__class__.__name__} failed: {exc}")