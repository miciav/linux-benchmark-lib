"""QThread worker for running benchmarks with UIHooks -> Qt signals bridge."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QThread, Signal

if TYPE_CHECKING:
    from lb_app.api import RunRequest, RunResult, RunEvent, RunJournal
    from lb_gui.services.app_client import AppClientService


class RunWorkerSignals(QObject):
    """Signals emitted by RunWorker.

    These bridge UIHooks callbacks to Qt's signal/slot mechanism,
    ensuring UI updates happen on the main thread.
    """

    # UIHooks mappings
    log_line = Signal(str)  # on_log
    status_line = Signal(str)  # on_status
    warning = Signal(str, float)  # on_warning (message, ttl)
    event_update = Signal(object)  # on_event (RunEvent)
    journal_update = Signal(object)  # on_journal (RunJournal)

    # Completion signal (not in UIHooks - emitted when start_run returns)
    finished = Signal(bool, str)  # (success, error_message or empty)


class UIHooksAdapter:
    """Adapter that implements UIHooks protocol and emits Qt signals."""

    def __init__(self, signals: RunWorkerSignals) -> None:
        self._signals = signals

    def on_log(self, line: str) -> None:
        """Forward log line to Qt signal."""
        self._signals.log_line.emit(line)

    def on_status(self, controller_state: str) -> None:
        """Forward status update to Qt signal."""
        self._signals.status_line.emit(controller_state)

    def on_warning(self, message: str, ttl: float = 10.0) -> None:
        """Forward warning to Qt signal with TTL."""
        self._signals.warning.emit(message, ttl)

    def on_event(self, event: "RunEvent") -> None:
        """Forward event to Qt signal."""
        self._signals.event_update.emit(event)

    def on_journal(self, journal: "RunJournal") -> None:
        """Forward journal update to Qt signal."""
        self._signals.journal_update.emit(journal)


class RunWorker(QObject):
    """Worker that runs benchmarks in a separate thread.

    Usage:
        worker = RunWorker(app_client_service, run_request)
        worker.signals.log_line.connect(on_log)
        worker.signals.finished.connect(on_finished)
        worker.start()
    """

    def __init__(
        self,
        app_client: "AppClientService",
        request: "RunRequest",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._app_client = app_client
        self._request = request
        self._thread: QThread | None = None
        self._result: "RunResult | None" = None

        # Create signals object
        self.signals = RunWorkerSignals()

    @property
    def result(self) -> "RunResult | None":
        """Get the run result after completion."""
        return self._result

    def start(self) -> None:
        """Start the worker in a new thread."""
        if self._thread is not None:
            return  # Already running

        self._thread = QThread()
        self.moveToThread(self._thread)
        self._thread.started.connect(self._run)
        self._thread.start()

    def _run(self) -> None:
        """Execute the benchmark run (called in worker thread)."""
        try:
            hooks = UIHooksAdapter(self.signals)
            self._result = self._app_client.start_run(self._request, hooks)

            if self._result is None:
                self.signals.finished.emit(False, "Run failed to start (validation error)")
            else:
                self.signals.finished.emit(True, "")
        except Exception as e:
            self.signals.finished.emit(False, str(e))
        finally:
            self._cleanup_thread()

    def _cleanup_thread(self) -> None:
        """Clean up the thread after completion."""
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
            self._thread.deleteLater()
            self._thread = None

    def is_running(self) -> bool:
        """Check if the worker is currently running."""
        return self._thread is not None and self._thread.isRunning()

    def wait(self, timeout_ms: int = -1) -> bool:
        """Wait for the worker to finish.

        Args:
            timeout_ms: Maximum time to wait in milliseconds (-1 = forever)

        Returns:
            True if finished, False if timed out
        """
        if self._thread is None:
            return True
        return self._thread.wait(timeout_ms)
