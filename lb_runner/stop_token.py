"""Stop token helpers for graceful interruption and file-based cancellation."""

from __future__ import annotations

import signal
from pathlib import Path
from typing import Callable, Dict, Optional


class StopToken:
    """
    Lightweight cooperative stop controller.

    It can be tripped by signals (SIGINT/SIGTERM) or by the presence of a stop
    file on disk. Consumers should call `should_stop()` in long-running loops
    and abort work when True.
    """

    def __init__(
        self,
        stop_file: Optional[Path] = None,
        enable_signals: bool = True,
        on_stop: Optional[Callable[[], None]] = None,
    ) -> None:
        self.stop_file = stop_file
        self._on_stop = on_stop
        self._stop_requested = False
        self._prev_handlers: Dict[int, Callable] = {}
        if enable_signals:
            self._install_signal_handlers()

    def _install_signal_handlers(self) -> None:
        """Capture SIGINT/SIGTERM and mark the token as stopped."""
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                self._prev_handlers[sig] = signal.getsignal(sig)
                signal.signal(sig, self._handle_signal)  # type: ignore[arg-type]
            except Exception:
                # Best effort; if signals cannot be set, continue without.
                continue

    def _handle_signal(self, signum: int, frame) -> None:  # type: ignore[override]
        self.request_stop()

    def request_stop(self) -> None:
        """Mark the token as stopped and trigger callback once."""
        if self._stop_requested:
            return
        self._stop_requested = True
        if self._on_stop:
            try:
                self._on_stop()
            except Exception:
                pass

    def should_stop(self) -> bool:
        """Return True when stop was requested or the stop file exists."""
        if self._stop_requested:
            return True
        if self.stop_file and self.stop_file.exists():
            self._stop_requested = True
            if self._on_stop:
                try:
                    self._on_stop()
                except Exception:
                    pass
            return True
        return False

    def restore(self) -> None:
        """Restore original signal handlers."""
        for sig, handler in self._prev_handlers.items():
            try:
                signal.signal(sig, handler)  # type: ignore[arg-type]
            except Exception:
                continue
        self._prev_handlers.clear()

    def __enter__(self) -> "StopToken":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.restore()
