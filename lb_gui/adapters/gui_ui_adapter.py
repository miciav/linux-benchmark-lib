"""UIAdapter implementation for GUI wiring."""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Sequence

from PySide6.QtCore import QObject

from lb_app.api import NoOpProgressHandle, ProgressHandle
from lb_gui.adapters.gui_dashboard_handle import GuiDashboardHandle, GuiDashboardSignals
from lb_gui.viewmodels.dashboard_vm import GUIDashboardViewModel


class GuiUIAdapter(QObject):
    """Bridge core UI callbacks to Qt viewmodels."""

    def __init__(self, dashboard_vm: GUIDashboardViewModel) -> None:
        super().__init__()
        self._vm = dashboard_vm
        self._signals = GuiDashboardSignals()
        self._signals.init_dashboard.connect(self._vm.initialize)
        self._signals.log_line.connect(self._vm.on_log_line)
        self._signals.refresh.connect(self._vm.refresh_snapshot)
        self._signals.warning.connect(self._vm.on_warning)
        self._signals.controller_state.connect(self._vm.on_status)

    def show_info(self, message: str) -> None:
        self._vm.on_status(message)

    def show_warning(self, message: str) -> None:
        self._vm.on_warning(message, 10.0)

    def show_error(self, message: str) -> None:
        self._vm.on_status(f"Error: {message}")

    def show_success(self, message: str) -> None:
        self._vm.on_status(message)

    def show_panel(
        self,
        message: str,
        title: str | None = None,
        border_style: str | None = None,
    ) -> None:
        _ = (title, border_style)
        self._vm.on_log_line(message)

    def show_rule(self, title: str) -> None:
        self._vm.on_log_line(title)

    def show_table(
        self, title: str, columns: Sequence[str], rows: list[Sequence[str]]
    ) -> None:
        _ = (title, columns, rows)

    def status(self, message: str):
        self._vm.on_status(message)
        return nullcontext()

    def create_progress(self, description: str, total: int) -> ProgressHandle:
        _ = (description, total)
        return NoOpProgressHandle()

    def create_dashboard(
        self,
        plan: list[dict[str, Any]],
        journal: Any,
        ui_log_file: Any | None = None,
    ) -> GuiDashboardHandle:
        _ = ui_log_file
        self._signals.init_dashboard.emit(plan, journal)
        return GuiDashboardHandle(self._signals)

    def prompt_multipass_scenario(
        self, options: list[str], default_level: str
    ) -> tuple[str, str] | None:
        _ = (options, default_level)
        return None
