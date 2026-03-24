"""Main application window with sidebar navigation."""

from __future__ import annotations

from typing import TYPE_CHECKING
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    QPushButton,
)

from lb_gui.resources.theme import (
    apply_theme,
    get_preferred_scale,
    get_preferred_theme,
    list_themes,
)

if TYPE_CHECKING:
    from lb_gui.app import ServiceContainer
    from lb_gui.viewmodels import (
        AnalyticsViewModel,
        ConfigViewModel,
        GUIDashboardViewModel,
        ResultsViewModel,
        RunSetupViewModel,
    )
    from lb_gui.workers import RunWorker
    from lb_app.api import RunRequest
    from lb_gui.services.run_orchestrator import RunOrchestrator


class MainWindow(QMainWindow):
    """Main application window with sidebar navigation."""

    # Navigation sections
    SECTIONS = [
        ("Run Setup", "run_setup"),
        ("Dashboard", "dashboard"),
        ("Results", "results"),
        ("Analytics", "analytics"),
        ("Config", "config"),
        ("Plugins", "plugins"),
        ("Doctor", "doctor"),
    ]

    def __init__(
        self, services: "ServiceContainer", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.services = services
        self._views: dict[str, QWidget] = {}
        self._viewmodels: dict[str, object] = {}
        self._current_worker: "RunWorker | None" = None
        self._current_stop_file: Path | None = None
        self._orchestrator: "RunOrchestrator | None" = None

        self._setup_ui()
        self._setup_views()
        self._connect_signals()
        self._setup_menu()

    def _setup_ui(self) -> None:
        """Set up the main UI layout."""
        self.setWindowTitle("Linux Benchmark")
        self.setMinimumSize(1200, 800)

        # Central widget with horizontal layout
        central = QWidget()
        central.setObjectName("mainRoot")
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Sidebar navigation
        self._sidebar = QListWidget()
        self._sidebar.setObjectName("sidebar")
        self._sidebar.setFixedWidth(180)
        self._sidebar.setSpacing(2)
        for label, _ in self.SECTIONS:
            item = QListWidgetItem(label)
            item.setSizeHint(
                item.sizeHint().expandedTo(
                    self._sidebar.sizeHint().scaled(
                        0, 40, Qt.AspectRatioMode.IgnoreAspectRatio
                    )
                )
            )
            self._sidebar.addItem(item)

        self._sidebar_container = QWidget()
        sidebar_layout = QVBoxLayout(self._sidebar_container)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(6)
        sidebar_layout.addWidget(self._sidebar)

        self._stop_button = QPushButton("Stop Run")
        self._stop_button.setEnabled(False)
        self._stop_button.clicked.connect(self._on_stop_clicked)
        sidebar_layout.addWidget(self._stop_button)

        # Stacked widget for views
        self._stack = QStackedWidget()

        main_layout.addWidget(self._sidebar_container)
        main_layout.addWidget(self._stack, 1)

    def _setup_views(self) -> None:
        """Create and add views with their viewmodels."""
        from lb_gui.viewmodels import (
            RunSetupViewModel,
            GUIDashboardViewModel,
            ResultsViewModel,
            AnalyticsViewModel,
            ConfigViewModel,
            PluginsViewModel,
            DoctorViewModel,
        )
        from lb_gui.views import (
            RunSetupView,
            DashboardView,
            ResultsView,
            AnalyticsView,
            ConfigView,
            PluginsView,
            DoctorView,
        )

        # Create viewmodels
        run_setup_vm = RunSetupViewModel(
            self.services.plugin_service,
            self.services.config_service,
        )
        dashboard_vm = GUIDashboardViewModel()
        results_vm = ResultsViewModel(
            self.services.run_catalog,
            self.services.config_service,
        )
        analytics_vm = AnalyticsViewModel(
            self.services.analytics_service,
            self.services.run_catalog,
            self.services.config_service,
        )
        config_vm = ConfigViewModel(self.services.config_service)
        plugins_vm = PluginsViewModel(
            self.services.plugin_service,
            self.services.config_service,
        )
        doctor_vm = DoctorViewModel(
            self.services.doctor_service,
            self.services.config_service,
        )

        # Store viewmodels
        self._viewmodels = {
            "run_setup": run_setup_vm,
            "dashboard": dashboard_vm,
            "results": results_vm,
            "analytics": analytics_vm,
            "config": config_vm,
            "plugins": plugins_vm,
            "doctor": doctor_vm,
        }

        # Create views with their viewmodels
        views = {
            "run_setup": RunSetupView(run_setup_vm),
            "dashboard": DashboardView(dashboard_vm),
            "results": ResultsView(results_vm),
            "analytics": AnalyticsView(analytics_vm),
            "config": ConfigView(config_vm),
            "plugins": PluginsView(plugins_vm),
            "doctor": DoctorView(doctor_vm),
        }

        # Add views to stack in order
        for _, key in self.SECTIONS:
            view = views[key]  # KeyError if a section is missing a view — explicit failure
            self._views[key] = view
            self._stack.addWidget(view)

        # Select first item by default
        self._sidebar.setCurrentRow(0)

        # Connect run setup to dashboard
        self._connect_run_flow(run_setup_vm, dashboard_vm)
        self._connect_config_flow(config_vm, run_setup_vm, results_vm, analytics_vm)

        # Ensure run setup reflects the currently loaded config (if any)
        if getattr(config_vm, "config", None) is not None:
            self._sync_config_to_views(
                config_vm, run_setup_vm, results_vm, analytics_vm
            )

    def _setup_menu(self) -> None:
        """Create the application menu."""
        menu_bar = self.menuBar()
        view_menu = menu_bar.addMenu("View")

        theme_menu = view_menu.addMenu("Theme")
        theme_group = QActionGroup(self)
        theme_group.setExclusive(True)

        current_theme = get_preferred_theme()
        for name in list_themes():
            action = theme_menu.addAction(name.replace("_", " ").title())
            action.setCheckable(True)
            action.setData(name)
            if name == current_theme:
                action.setChecked(True)
            theme_group.addAction(action)

        def on_theme_selected(action: QAction) -> None:
            app = QApplication.instance()
            if not isinstance(app, QApplication):
                return
            apply_theme(app, action.data(), save=True)

        theme_group.triggered.connect(on_theme_selected)

        scale_menu = view_menu.addMenu("UI Scale")
        scale_group = QActionGroup(self)
        scale_group.setExclusive(True)

        current_scale = get_preferred_scale()
        scale_options = [
            ("100%", 1.0),
            ("115%", 1.15),
            ("130%", 1.3),
        ]
        for label, scale in scale_options:
            action = scale_menu.addAction(label)
            action.setCheckable(True)
            action.setData(scale)
            if abs(scale - current_scale) < 0.01:
                action.setChecked(True)
            scale_group.addAction(action)

        def on_scale_selected(action: QAction) -> None:
            app = QApplication.instance()
            if not isinstance(app, QApplication):
                return
            apply_theme(app, scale=action.data(), save=True)

        scale_group.triggered.connect(on_scale_selected)

    def _connect_run_flow(
        self,
        run_setup_vm: "RunSetupViewModel",
        dashboard_vm: "GUIDashboardViewModel",
    ) -> None:
        """Connect run setup to dashboard for run execution flow."""
        from lb_gui.services.run_orchestrator import RunOrchestrator
        from lb_gui.views.run_setup_view import RunSetupView

        run_setup_view = self._views.get("run_setup")
        if not isinstance(run_setup_view, RunSetupView):
            return

        self._orchestrator = RunOrchestrator(self.services.run_controller, dashboard_vm)

        def on_start_run(request: "RunRequest") -> None:
            try:
                worker = self._orchestrator.start_run(request)
            except RuntimeError as exc:
                QMessageBox.warning(self, "Run In Progress", str(exc))
                return
            except Exception as exc:
                QMessageBox.warning(self, "Error", f"Failed to get run plan:\n{exc}")
                return

            self._current_worker = worker
            self._current_stop_file = getattr(request, "stop_file", None)
            worker.signals.finished.connect(self._on_run_finished)

            self.select_section("dashboard")
            # _set_ui_busy(True) is called AFTER orchestrator.start_run() returns
            # successfully. If start_run() raises, the except blocks above return
            # early before reaching this line, so the cursor is never set and no
            # cleanup is needed.
            self._set_ui_busy(True)

        run_setup_view.start_run_requested.connect(on_start_run)

    def _set_ui_busy(self, busy: bool) -> None:
        """Enable or disable UI interaction during run."""
        self._sidebar.setEnabled(not busy)
        is_running = bool(busy and self._current_worker and self._current_worker.is_running())
        self._stop_button.setEnabled(is_running)
        if busy:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        else:
            QApplication.restoreOverrideCursor()

    def _on_run_finished(self, success: bool, error: str) -> None:
        """Handle run completion to restore UI state."""
        self._set_ui_busy(False)
        self._current_worker = None
        self._current_stop_file = None

        if not success:
            QMessageBox.critical(
                self,
                "Run Failed",
                f"Benchmark run failed or completed with error:\n{error}",
            )

    def _on_stop_clicked(self) -> None:
        """Handle stop button click with confirmation."""
        stop_path = self._current_stop_file
        if not stop_path:
            QMessageBox.warning(
                self,
                "Stop Run",
                "Stop file path not available for this run.",
            )
            return
        reply = QMessageBox.question(
            self,
            "Stop Run",
            "Gracefully stop the current run?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            stop_path = Path(stop_path)
            stop_path.parent.mkdir(parents=True, exist_ok=True)
            stop_path.write_text("stop")
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Stop Failed",
                f"Failed to write stop file:\n{exc}",
            )
            return
        if hasattr(self, "_stop_button"):
            self._stop_button.setEnabled(False)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle window close request."""
        worker = self._current_worker
        if worker is not None and worker.is_running():
            reply = QMessageBox.question(
                self,
                "Benchmark Running",
                "A benchmark is currently running. Closing the application may leave "
                "remote processes active.\n\nAre you sure you want to force quit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return

        event.accept()

    def _connect_config_flow(
        self,
        config_vm: "ConfigViewModel",
        run_setup_vm: "RunSetupViewModel",
        results_vm: "ResultsViewModel",
        analytics_vm: "AnalyticsViewModel",
    ) -> None:
        """Connect config changes to dependent views."""
        def on_config_loaded(_: object) -> None:
            self._sync_config_to_views(
                config_vm, run_setup_vm, results_vm, analytics_vm
            )

        config_vm.config_loaded.connect(on_config_loaded)

    def _sync_config_to_views(
        self,
        config_vm: "ConfigViewModel",
        run_setup_vm: "RunSetupViewModel",
        results_vm: "ResultsViewModel",
        analytics_vm: "AnalyticsViewModel",
    ) -> None:
        """Apply the loaded config to views that depend on it."""
        config_path = getattr(config_vm, "config_path", None)
        config_obj = getattr(config_vm, "config", None)

        if config_obj is not None:
            run_setup_vm.set_config(config_obj)
            run_setup_vm.refresh_workloads()
        elif config_path is not None:
            run_setup_vm.load_config(config_path)
            run_setup_vm.refresh_workloads()

        self._apply_config_to_catalog_vm(results_vm, config_obj, config_path)
        self._apply_config_to_catalog_vm(analytics_vm, config_obj, config_path)

    def _apply_config_to_catalog_vm(
        self,
        vm: object,
        config_obj: object | None,
        config_path: object | None,
    ) -> None:
        """Apply config to a ResultsViewModel or AnalyticsViewModel."""
        if config_obj is not None:
            vm.configure_with_config(config_obj)  # type: ignore[union-attr]
            vm.refresh_runs()  # type: ignore[union-attr]
        elif config_path is not None:
            if vm.configure(config_path):  # type: ignore[union-attr]
                vm.refresh_runs()  # type: ignore[union-attr]

    def _connect_signals(self) -> None:
        """Connect UI signals."""
        self._sidebar.currentRowChanged.connect(self._on_section_changed)

    def _on_section_changed(self, row: int) -> None:
        """Handle sidebar selection change."""
        if 0 <= row < len(self.SECTIONS):
            self._stack.setCurrentIndex(row)

    def get_view(self, key: str) -> QWidget | None:
        """Get a view by its key."""
        return self._views.get(key)

    def get_viewmodel(self, key: str) -> object | None:
        """Get a viewmodel by its key."""
        return self._viewmodels.get(key)

    def select_section(self, key: str) -> None:
        """Programmatically select a section by key."""
        for i, (_, section_key) in enumerate(self.SECTIONS):
            if section_key == key:
                self._sidebar.setCurrentRow(i)
                break
