"""GUI dashboard handle and signals for core wiring."""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any

from PySide6.QtCore import QObject, Signal

from lb_app.api import DashboardHandle


class GuiDashboardSignals(QObject):
    """Signals emitted by GUI dashboard handle."""

    init_dashboard = Signal(object, object)
    log_line = Signal(str)
    refresh = Signal()
    warning = Signal(str, float)
    controller_state = Signal(str)


class GuiDashboardHandle(DashboardHandle):
    """Dashboard handle that forwards updates via Qt signals."""

    def __init__(self, signals: GuiDashboardSignals) -> None:
        self._signals = signals

    def live(self):
        return nullcontext()

    def add_log(self, line: str) -> None:
        if line:
            self._signals.log_line.emit(str(line))

    def refresh(self) -> None:
        self._signals.refresh.emit()

    def mark_event(self, source: str) -> None:
        _ = source

    def set_warning(self, message: str, ttl: float = 10.0) -> None:
        self._signals.warning.emit(message, ttl)

    def set_controller_state(self, state: str) -> None:
        self._signals.controller_state.emit(state)

    def __getattr__(self, name: str) -> Any:
        # Allow optional methods without breaking protocol expectations.
        raise AttributeError(name)
