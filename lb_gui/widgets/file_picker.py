"""File picker widget with line edit and browse button."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLineEdit, QPushButton, QWidget


class FilePicker(QWidget):
    """Widget for selecting a file or directory."""

    path_changed = Signal(str)

    def __init__(
        self,
        parent: object | None = None,
        *,
        placeholder: str = "",
        dialog_title: str = "Select file",
        mode: str = "open",
    ) -> None:
        super().__init__(parent)
        self._dialog_title = dialog_title
        self._mode = mode  # "open", "save", "dir"

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._line_edit = QLineEdit()
        if placeholder:
            self._line_edit.setPlaceholderText(placeholder)
        self._line_edit.textChanged.connect(self.path_changed.emit)

        self._button = QPushButton("Browse")
        self._button.clicked.connect(self._on_browse)

        layout.addWidget(self._line_edit, 1)
        layout.addWidget(self._button)

    def set_path(self, path: str) -> None:
        """Set the current path."""
        self._line_edit.setText(path)

    def path(self) -> str:
        """Get the current path."""
        return self._line_edit.text().strip()

    def _on_browse(self) -> None:
        """Open a file dialog based on the configured mode."""
        if self._mode == "dir":
            path = QFileDialog.getExistingDirectory(self, self._dialog_title)
        elif self._mode == "save":
            path, _ = QFileDialog.getSaveFileName(self, self._dialog_title)
        else:
            path, _ = QFileDialog.getOpenFileName(self, self._dialog_title)

        if path:
            self._line_edit.setText(path)
