from __future__ import annotations

import sys
from contextlib import contextmanager
from dataclasses import dataclass
from typing import IO, Sequence

from ._shared import format_table
from .types import ProgressHandle, UIAdapter


@dataclass
class _Progress(ProgressHandle):
    """Lightweight progress tracker for headless mode."""

    description: str
    total: int
    stream: IO[str]
    last_written: int = 0

    def update(self, completed: int) -> None:
        completed = min(completed, self.total)
        if completed == self.last_written:
            return
        self.last_written = completed
        percent = int((completed / self.total) * 100) if self.total else 100
        self.stream.write(f"\r{self.description}: {percent}%")
        self.stream.flush()

    def finish(self) -> None:
        self.update(self.total)
        self.stream.write("\n")
        self.stream.flush()


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

    def create_progress(self, description: str, total: int) -> ProgressHandle:
        return _Progress(description=description, total=total, stream=self.stream)
