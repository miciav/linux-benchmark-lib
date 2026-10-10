"""QThread worker that runs one analytics job (prepare or write)."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QThread, Signal


class AnalyticsWorkerSignals(QObject):
    """Signals emitted by AnalyticsWorker."""

    finished = Signal(object)  # the job's result
    failed = Signal(str)


class AnalyticsWorker(QObject):
    """Worker that runs a callable in a separate thread."""

    def __init__(
        self, job: Callable[[], object], parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._job = job
        self._thread: QThread | None = None
        self.signals = AnalyticsWorkerSignals()

    def start(self) -> None:
        """Start the worker in a new thread."""
        if self._thread is not None:
            return
        self._thread = QThread()
        self.moveToThread(self._thread)
        self._thread.started.connect(self._run)
        self._thread.finished.connect(self._clear_thread)
        self._thread.start()

    def _clear_thread(self) -> None:
        """Release the thread reference once the thread has fully stopped."""
        self._thread = None

    def _run(self) -> None:
        try:
            self.signals.finished.emit(self._job())
        except Exception as exc:
            self.signals.failed.emit(str(exc))
        finally:
            QThread.currentThread().quit()

    def is_running(self) -> bool:
        """Check if the worker is currently running."""
        return self._thread is not None
