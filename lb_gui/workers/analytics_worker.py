"""QThread worker for running analytics asynchronously."""

from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

from PySide6.QtCore import QObject, QThread, Signal

if TYPE_CHECKING:
    from lb_app.api import AnalyticsKind
    from lb_common.api import RunInfo
    from lb_gui.services.analytics_service import AnalyticsServiceWrapper


class AnalyticsWorkerSignals(QObject):
    """Signals emitted by AnalyticsWorker."""

    finished = Signal(list)  # list[Path]
    failed = Signal(str)


class AnalyticsWorker(QObject):
    """Worker that runs analytics in a separate thread."""

    def __init__(
        self,
        analytics_service: "AnalyticsServiceWrapper",
        run_info: "RunInfo",
        kind: "AnalyticsKind",
        workloads: Sequence[str] | None = None,
        hosts: Sequence[str] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._analytics = analytics_service
        self._run_info = run_info
        self._kind = kind
        self._workloads = workloads
        self._hosts = hosts
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
        """Execute analytics in the worker thread."""
        try:
            artifacts = self._analytics.run_analytics(
                run_info=self._run_info,
                kind=self._kind,
                workloads=self._workloads,
                hosts=self._hosts,
            )
            self.signals.finished.emit(list(artifacts))
        except Exception as exc:
            self.signals.failed.emit(str(exc))
        finally:
            QThread.currentThread().quit()

    def is_running(self) -> bool:
        """Check if the worker is currently running."""
        return self._thread is not None
