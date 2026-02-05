"Webhook notification provider."

from __future__ import annotations

import json
import logging
import urllib.request
import urllib.error
from typing import Any, Dict

from lb_ui.notifications.base import NotificationProvider, NotificationContext

logger = logging.getLogger(__name__)


class WebhookProvider(NotificationProvider):
    """Sends notifications via HTTP POST payload."""

    def __init__(self, url: str, timeout_seconds: int = 5):
        self.url = url
        self.timeout = timeout_seconds

    def send(self, context: NotificationContext) -> None:
        """Send JSON payload to the configured webhook URL."""
        payload = self._build_payload(context)

        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                self.url,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": f"LB-Runner/{context.app_name}",
                },
            )

            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status >= 400:
                    logger.warning(f"Webhook provider returned status {resp.status}")

        except urllib.error.URLError as exc:
            logger.warning(f"Webhook connection failed: {exc.reason}")
        except Exception as exc:
            logger.debug(f"Webhook delivery failed: {exc}")

    def _build_payload(self, context: NotificationContext) -> Dict[str, Any]:
        """Construct the JSON payload."""
        status_emoji = "✅" if context.success else "❌"
        duration_text = ""
        if context.duration_s is not None:
            duration_text = f" ({context.duration_s:.1f}s)"

        header = f"{status_emoji} {context.title}{duration_text}"

        # Simple text formatting
        text = f"*{header}*\n{context.message}"

        return {
            "text": text,
            "title": context.title,
            "message": context.message,
            "status": "success" if context.success else "failed",
            "run_id": context.run_id,
            "duration": context.duration_s,
        }
