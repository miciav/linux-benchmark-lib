from __future__ import annotations


class UIFlowError(RuntimeError):
    """Typed error for UI flow failures that should be handled by CLI."""

    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code
