"""Default dashboard implementation with no-op handlers."""

from __future__ import annotations

from contextlib import nullcontext
from typing import ContextManager

from lb_ui.tui.system.protocols import Dashboard


class DashboardNoOp(Dashboard):
    """No-op dashboard implementation used as a base for adapters/sinks."""

    def live(self) -> ContextManager[None]:
        return nullcontext()

    def add_log(self, line: str) -> None:
        return None

    def refresh(self) -> None:
        return None

    def mark_event(self, source: str) -> None:
        return None

    def set_warning(self, message: str, ttl: float = 10.0) -> None:
        return None

    def clear_warning(self) -> None:
        return None

    def set_controller_state(self, state: str) -> None:
        return None
