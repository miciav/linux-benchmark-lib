from __future__ import annotations

from contextlib import nullcontext
from typing import ContextManager

from lb_ui.tui.core.protocols import Dashboard, PresenterSink


class Presenter:
    def __init__(self, sink: PresenterSink) -> None:
        self._sink = sink

    def info(self, message: str) -> None:
        self._sink.emit("info", message)

    def warning(self, message: str) -> None:
        self._sink.emit("warning", message)

    def error(self, message: str) -> None:
        self._sink.emit("error", message)

    def success(self, message: str) -> None:
        self._sink.emit("success", message)

    def panel(
        self,
        message: str,
        title: str | None = None,
        border_style: str | None = None,
    ) -> None:
        self._sink.emit_panel(message, title, border_style)

    def rule(self, title: str) -> None:
        self._sink.emit_rule(title)


class NullDashboard(Dashboard):
    def live(self) -> ContextManager[None]:
        return nullcontext()

    def add_log(self, line: str) -> None:
        _ = line

    def refresh(self) -> None:
        return None

    def mark_event(self, source: str) -> None:
        _ = source

    def set_warning(self, message: str, ttl: float = 10.0) -> None:
        _ = (message, ttl)

    def clear_warning(self) -> None:
        return None

    def set_controller_state(self, state: str) -> None:
        _ = state


DashboardNoOp = NullDashboard

__all__ = ["Presenter", "NullDashboard", "DashboardNoOp"]
