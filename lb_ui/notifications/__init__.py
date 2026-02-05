"""Notification system entry point."""

from lb_ui.notifications.manager import NotificationManager

_MANAGER = NotificationManager()


def send_notification(
    title: str,
    message: str,
    success: bool = True,
    run_id: str | None = None,
    duration_s: float | None = None,
) -> None:
    """Send a system notification using the global manager."""
    _MANAGER.send(
        title=title,
        message=message,
        success=success,
        run_id=run_id,
        duration_s=duration_s,
    )
