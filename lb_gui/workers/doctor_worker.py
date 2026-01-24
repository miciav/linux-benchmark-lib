"""QThread worker for running doctor checks asynchronously."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QThread, Signal

if TYPE_CHECKING:
    from lb_app.api import BenchmarkConfig, DoctorReport
    from lb_gui.services.doctor_service import DoctorServiceWrapper


class DoctorWorkerSignals(QObject):
    """Signals emitted by DoctorWorker."""

    progress = Signal(str)
    finished = Signal(list)  # list[DoctorReport]
    failed = Signal(str)


class DoctorWorker(QObject):
    """Worker that runs doctor checks in a separate thread."""

    def __init__(
        self,
        doctor_service: "DoctorServiceWrapper",
        config: "BenchmarkConfig | None",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._doctor = doctor_service
        self._config = config
        self._thread: QThread | None = None

        self.signals = DoctorWorkerSignals()

    def start(self) -> None:
        """Start the worker in a new thread."""
        if self._thread is not None:
            return
        self._thread = QThread()
        self.moveToThread(self._thread)
        self._thread.started.connect(self._run)
        self._thread.start()

    def _run(self) -> None:
        """Execute doctor checks in the worker thread."""
        try:
            reports: list["DoctorReport"] = []

            self.signals.progress.emit("Checking controller dependencies...")
            reports.append(self._doctor.check_controller())

            self.signals.progress.emit("Checking local tools...")
            reports.append(self._doctor.check_local_tools())

            if self._config is not None and self._config.remote_hosts:
                self.signals.progress.emit("Checking remote connectivity...")
                reports.append(self._doctor.check_connectivity(self._config))

            self.signals.finished.emit(reports)
        except Exception as exc:
            self.signals.failed.emit(str(exc))
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
