"""ViewModel for the Analytics view: experiment unification."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QCoreApplication, QObject, Signal

from lb_gui.utils import format_datetime
from lb_gui.workers import AnalyticsWorker

if TYPE_CHECKING:
    from lb_app.api import (
        BenchmarkConfig,
        ExperimentInfo,
        UnificationPreview,
    )
    from lb_gui.services import GUIConfigService, RunCatalogServiceWrapper


class AnalyticsViewModel(QObject):
    """State of the Analytics view; the work is UnificationService's."""

    experiments_changed = Signal(list)  # list[ExperimentInfo]
    experiment_selected = Signal(object)  # ExperimentInfo | None
    preview_changed = Signal(object)  # UnificationPreview | None
    analytics_started = Signal()
    analytics_completed = Signal(list)  # list[Path]
    analytics_failed = Signal(str)
    error_occurred = Signal(str)

    def __init__(
        self,
        run_catalog: RunCatalogServiceWrapper,
        config_service: GUIConfigService | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._run_catalog = run_catalog
        self._config_service = config_service
        self._experiments: list[ExperimentInfo] = []
        self._selected: ExperimentInfo | None = None
        self._selected_hosts: list[str] = []
        self._selected_workloads: list[str] = []
        self._preview: UnificationPreview | None = None
        self._last_artifacts: list[Path] = []
        self._worker: AnalyticsWorker | None = None
        self._pending: Callable[[object], None] | None = None
        self._busy = False
        # Bumped on every selection or filter change; a preview prepared for
        # an older generation arrives stale and is dropped.
        self._generation = 0
        self._prepared_for = -1
        self._last_written: UnificationPreview | None = None
        self._writing: UnificationPreview | None = None
        self._is_configured: bool = config_service is None

    @property
    def experiments(self) -> list[ExperimentInfo]:
        return self._experiments

    @property
    def selected_experiment(self) -> ExperimentInfo | None:
        return self._selected

    @property
    def available_hosts(self) -> list[str]:
        return self._selected.hosts if self._selected else []

    @property
    def available_workloads(self) -> list[str]:
        return self._selected.workloads if self._selected else []

    @property
    def selected_hosts(self) -> list[str]:
        return self._selected_hosts

    @selected_hosts.setter
    def selected_hosts(self, value: list[str]) -> None:
        self._selected_hosts = value
        self._set_preview(None)

    @property
    def selected_workloads(self) -> list[str]:
        return self._selected_workloads

    @selected_workloads.setter
    def selected_workloads(self, value: list[str]) -> None:
        self._selected_workloads = value
        self._set_preview(None)

    @property
    def preview(self) -> UnificationPreview | None:
        return self._preview

    @property
    def can_unify(self) -> bool:
        return self._preview is not None and not self._preview.is_empty

    @property
    def last_artifacts(self) -> list[Path]:
        return self._last_artifacts

    @property
    def last_written(self) -> UnificationPreview | None:
        """The preview the last successful unify wrote."""
        return self._last_written

    @property
    def is_busy(self) -> bool:
        return self._busy

    def refresh_runs(self) -> None:
        """Reload the experiments list (folder entry first)."""
        if not self._is_configured and not self.configure():
            return
        try:
            targets = self._run_catalog.unification().list_targets()
        except Exception as exc:
            self.error_occurred.emit(f"Failed to list experiments: {exc}")
            targets = []
            self._is_configured = False
        folder = [t for t in targets if t.kind == "folder"]
        self._experiments = folder + [t for t in targets if t.kind != "folder"]
        self.experiments_changed.emit(self._experiments)
        # Rows may have moved: never keep an old selection behind a new table.
        self.select_experiment(None)

    def configure(self, config_path: Path | None = None) -> bool:
        """Configure the run catalog service using the benchmark config."""
        if self._config_service is None:
            self._is_configured = True
            return True
        if config_path is None:
            try:
                current = self._config_service.get_current_config()
                cached = current[0] if isinstance(current, tuple) and current else None
            except Exception:
                cached = None
            if cached is not None:
                self.configure_with_config(cached)
                return True
        try:
            config, resolved, _ = self._config_service.load_config(config_path)
            self._run_catalog.configure(config, resolved)
            self._is_configured = True
            return True
        except Exception as e:
            self.error_occurred.emit(f"Failed to load config: {e}")
            self._is_configured = False
            return False

    def configure_with_config(self, config: BenchmarkConfig) -> None:
        """Configure the run catalog service with a preloaded config."""
        self._run_catalog.configure(config, self._current_config_path())
        self._is_configured = True

    def _current_config_path(self) -> Path | None:
        """Where the loaded config came from, for the equivalent command."""
        if self._config_service is None:
            return None
        try:
            current = self._config_service.get_current_config()
        except Exception:
            return None
        if isinstance(current, tuple) and len(current) > 1:
            return current[1]
        return None

    def select_experiment(self, index: int | None) -> None:
        """Select by row; the filters default to every host and workload."""
        valid = index is not None and 0 <= index < len(self._experiments)
        self._selected = (
            self._experiments[index] if valid and index is not None else None
        )
        self._selected_hosts = list(self.available_hosts)
        self._selected_workloads = list(self.available_workloads)
        self._set_preview(None)
        self.experiment_selected.emit(self._selected)

    def prepare(self) -> None:
        """Load the selection in the background and publish its preview."""
        experiment = self._selected
        if experiment is None:
            self.analytics_failed.emit("No experiment selected")
            return
        if not self._selected_hosts or not self._selected_workloads:
            # Nothing selected is not "all": the summary would say otherwise.
            self.analytics_failed.emit("Select at least one host and one workload")
            return
        service = self._run_catalog.unification()
        hosts, workloads = list(self._selected_hosts), list(self._selected_workloads)
        self._prepared_for = self._generation
        self._start(
            lambda: service.prepare(experiment, hosts, workloads), self._on_prepared
        )

    def unify(self) -> None:
        """Write the prepared preview in the background."""
        preview = self._preview
        if preview is None or preview.is_empty:
            self.analytics_failed.emit("Prepare a non-empty unification first")
            return
        service = self._run_catalog.unification()
        self._writing = preview
        self._start(lambda: service.write(preview), self._on_written)

    def get_experiment_rows(self) -> list[list[str]]:
        rows = []
        for target in self._experiments:
            name = (
                f"Folder {target.id} (all runs)"
                if target.kind == "folder"
                else target.id
            )
            rows.append(
                [
                    name,
                    str(len(target.runs)),
                    ", ".join(target.hosts),
                    ", ".join(target.workloads),
                    format_datetime(target.last_created),
                ]
            )
        return rows

    def _set_preview(self, preview: UnificationPreview | None) -> None:
        if preview is None:
            self._generation += 1
        self._preview = preview
        self.preview_changed.emit(preview)

    def _on_prepared(self, preview: object) -> None:
        if self._prepared_for != self._generation:
            return  # the selection or filters changed while it was loading
        self._set_preview(preview)  # type: ignore[arg-type]

    def _on_written(self, paths: object) -> None:
        self._last_written = self._writing
        self._last_artifacts = list(paths)  # type: ignore[call-overload]
        self.analytics_completed.emit(self._last_artifacts)

    def _start(
        self, job: Callable[[], object], on_done: Callable[[object], None]
    ) -> None:
        if self._busy or (self._worker is not None and self._worker.is_running()):
            return
        self._busy = True
        self.analytics_started.emit()
        if QCoreApplication.instance() is None or os.environ.get("PYTEST_CURRENT_TEST"):
            try:
                result = job()
            except Exception as exc:
                self._busy = False
                self.analytics_failed.emit(str(exc))
                return
            self._busy = False
            on_done(result)
            return
        self._pending = on_done
        self._worker = AnalyticsWorker(job)
        # Bound methods of this QObject, so the slots run on the GUI thread.
        self._worker.signals.finished.connect(self._on_worker_finished)
        self._worker.signals.failed.connect(self._on_worker_failed)
        self._worker.start()

    # The worker reference is kept until the next job: dropping it here could
    # destroy its QThread while that thread is still leaving its event loop.
    def _on_worker_finished(self, result: object) -> None:
        self._busy = False
        if self._pending is not None:
            self._pending(result)

    def _on_worker_failed(self, error: str) -> None:
        self._busy = False
        self.analytics_failed.emit(error)
