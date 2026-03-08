"""Stop token helpers for graceful interruption and file-based cancellation."""

from __future__ import annotations

import signal
from pathlib import Path
from types import FrameType, TracebackType
from typing import Callable, Optional

SignalHandler = int | Callable[[int, FrameType | None], object]


def _as_callable_handler(
    handler: SignalHandler | None,
) -> Callable[[int, FrameType | None], object] | None:
    """Return the previous signal handler when it is callable."""
    if callable(handler):
        return handler
    return None


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
        self._prev_handlers: dict[int, SignalHandler | None] = {}
        if enable_signals:
            self._install_signal_handlers()

    def _install_signal_handlers(self) -> None:
        """Capture SIGINT/SIGTERM and mark the token as stopped."""
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                self._prev_handlers[sig] = signal.getsignal(sig)
                signal.signal(sig, self._handle_signal)
            except Exception:
                # Best effort; if signals cannot be set, continue without.
                continue

    def _handle_signal(self, signum: int, frame: FrameType | None) -> None:
        if self._stop_requested:
            prev_handler = self._prev_handlers.get(signum)
            if prev_handler is None or prev_handler == signal.SIG_IGN:
                return
            if prev_handler == signal.SIG_DFL:
                signal.default_int_handler(signum, frame)
            callable_handler = _as_callable_handler(prev_handler)
            if callable_handler is None:
                signal.default_int_handler(signum, frame)
            try:
                callable_handler(signum, frame)
            except Exception:
                # Fall back to default if the previous handler misbehaves.
                signal.default_int_handler(signum, frame)
            return
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
            if handler is None:
                continue
            try:
                signal.signal(sig, handler)
            except Exception:
                continue
        self._prev_handlers.clear()

    def __enter__(self) -> "StopToken":
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        self.restore()
