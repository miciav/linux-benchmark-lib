from __future__ import annotations

from typing import Protocol

from lb_ui.tui.system.protocols import Presenter


class PresenterSink(Protocol):
    def emit(self, level: str, message: str) -> None: ...

    def emit_panel(
        self,
        message: str,
        title: str | None,
        border_style: str | None,
    ) -> None: ...

    def emit_rule(self, title: str) -> None: ...


class PresenterBase(Presenter):
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
