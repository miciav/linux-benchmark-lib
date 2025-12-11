"""Headless UI adapter for deterministic test-friendly output."""

from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import IO, Sequence

from lb_controller.ui_interfaces import DashboardHandle, UIAdapter
from lb_ui.ui.dashboard import NoopDashboard
from lb_ui.ui.progress import StreamProgressHandle
from lb_ui.ui.utils import format_table


class HeadlessUIAdapter(UIAdapter):
    """A deterministic, print-based UI adapter suitable for tests and non-TTY runs."""

    def __init__(self, stream: IO[str] | None = None):
        self.stream = stream or sys.stdout

    def _write(self, text: str) -> None:
        self.stream.write(text + "\n")
        self.stream.flush()

    def show_info(self, message: str) -> None:
        self._write(f"[INFO] {message}")

    def show_warning(self, message: str) -> None:
        self._write(f"[WARN] {message}")

    def show_error(self, message: str) -> None:
        self._write(f"[ERROR] {message}")

    def show_success(self, message: str) -> None:
        self._write(f"[SUCCESS] {message}")

    def show_panel(self, message: str, title: str | None = None, border_style: str | None = None) -> None:
        header = f"[{title}] " if title else ""
        self._write(f"{header}{message}")

    def show_rule(self, title: str) -> None:
        self._write(f"--- {title} ---")

    def show_table(self, title: str, columns: Sequence[str], rows: list[Sequence[str]]) -> None:
        self._write(format_table(title, columns, rows))

    @contextmanager
    def status(self, message: str):
        self._write(f"{message}...")
        try:
            yield
            self._write("Done.")
        except Exception:
            self._write("Failed.")
            raise

    def create_progress(self, description: str, total: int):
        return StreamProgressHandle(description=description, total=total, stream=self.stream)

    def create_dashboard(self, plan: list[dict], journal: any) -> DashboardHandle:
        return NoopDashboard()

    def prompt_multipass_scenario(self, options: list[str], default_level: str):
        return None
