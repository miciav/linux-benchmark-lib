"""Log viewer widget for streaming output."""

from __future__ import annotations

from PySide6.QtWidgets import QPlainTextEdit


class LogViewer(QPlainTextEdit):
    """Read-only log viewer with auto-scroll."""

    def __init__(self, parent: object | None = None, max_lines: int = 10000) -> None:
        super().__init__(parent)
        self.setObjectName("logViewer")
        self.setReadOnly(True)
        self.setMaximumBlockCount(max_lines)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

    def append_line(self, line: str) -> None:
        """Append a line and keep the view scrolled to the bottom."""
        self.appendPlainText(line.rstrip())
        scrollbar = self.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
