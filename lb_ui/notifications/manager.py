"""Notification manager orchestrating providers."""

from __future__ import annotations

import atexit
import logging
import os
import queue
import threading
from typing import List, Optional

from lb_ui.notifications.base import NotificationContext, NotificationProvider
from lb_ui.notifications.providers.desktop import DesktopProvider
from lb_ui.notifications.providers.webhook import WebhookProvider
from lb_ui.services.assets import resolve_icon_path

logger = logging.getLogger(__name__)


class NotificationManager:
    """Orchestrates notification delivery asynchronously."""

    def __init__(self, app_name: str = "Linux Benchmark Lib") -> None:
        self.app_name = app_name
        self._providers: List[NotificationProvider] = []
        self._queue: queue.Queue[Optional[NotificationContext]] = queue.Queue()
        self._initialize_providers()
        
        # Start worker thread
        self._worker_thread = threading.Thread(target=self._worker_loop, name="NotifyWorker", daemon=True)
        self._worker_thread.start()
        
        # Ensure we try to flush on exit
        atexit.register(self.shutdown)

    def _initialize_providers(self) -> None:
        """Load enabled providers based on environment/config."""
        self._providers.append(DesktopProvider(self.app_name))

        webhook_url = os.environ.get("LB_WEBHOOK_URL")
        if webhook_url:
            self._providers.append(WebhookProvider(webhook_url))

    def _worker_loop(self) -> None:
        """Consumes notifications from the queue and dispatches them."""
        while True:
            context = self._queue.get()
            if context is None:
                # Sentinel received, shutdown
                self._queue.task_done()
                break
            
            self._dispatch(context)
            self._queue.task_done()

    def _dispatch(self, context: NotificationContext) -> None:
        """Synchronously dispatch to all providers."""
        for provider in self._providers:
            try:
                provider.send(context)
            except Exception as exc:
                logger.error(
                    f"Failed to send notification via {provider.__class__.__name__}: {exc}"
                )

    def send(
        self,
        title: str,
        message: str,
        success: bool = True,
        run_id: Optional[str] = None,
        duration_s: Optional[float] = None,
    ) -> None:
        """Enqueue a notification for delivery."""
        
        # Enrich context
        if duration_s is not None:
            message += f"\nDuration: {duration_s:.1f}s"
        if run_id:
            title = f"Run {run_id}: {title}"

        context = NotificationContext(
            title=title,
            message=message,
            success=success,
            app_name=self.app_name,
            icon_path=resolve_icon_path(),
            run_id=run_id,
            duration_s=duration_s
        )
        
        self._queue.put(context)

    def shutdown(self, timeout: float = 5.0) -> None:
        """Gracefully stop the worker, waiting for pending notifications."""
        if not self._worker_thread.is_alive():
            return
            
        # Send sentinel
        self._queue.put(None)
        self._worker_thread.join(timeout=timeout)