"""Base interface for notification providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class NotificationContext:
    """Context data for a notification event."""

    title: str
    message: str
    success: bool
    app_name: str
    icon_path: str | None = None
    run_id: str | None = None
    duration_s: float | None = None


class NotificationProvider(ABC):
    """Abstract base class for a notification delivery mechanism."""

    @abstractmethod
    def send(self, context: NotificationContext) -> None:
        """Deliver the notification based on the provided context."""
        pass
