"""Main application window with sidebar navigation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from lb_gui.resources.theme import (
    apply_theme,
    get_preferred_scale,
    get_preferred_theme,
    list_themes,
)

if TYPE_CHECKING:
    from lb_gui.app import ServiceContainer


class PlaceholderView(QWidget):
    """Temporary placeholder for views not yet implemented."""

    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        label = QLabel(f"{name}\n\n(Not yet implemented)")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)


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

    def __init__(self, services: "ServiceContainer", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self._views: dict[str, QWidget] = {}
        self._viewmodels: dict[str, object] = {}

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
            item.setSizeHint(item.sizeHint().expandedTo(
                self._sidebar.sizeHint().scaled(0, 40, Qt.AspectRatioMode.IgnoreAspectRatio)
            ))
            self._sidebar.addItem(item)

        # Stacked widget for views
        self._stack = QStackedWidget()

        main_layout.addWidget(self._sidebar)
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
            view = views.get(key)
            if view:
                self._views[key] = view
                self._stack.addWidget(view)
            else:
                placeholder = PlaceholderView(key)
                self._views[key] = placeholder
                self._stack.addWidget(placeholder)

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

        def on_theme_selected(action) -> None:  # type: ignore[no-untyped-def]
            app = QApplication.instance()
            if app is None:
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

        def on_scale_selected(action) -> None:  # type: ignore[no-untyped-def]
            app = QApplication.instance()
            if app is None:
                return
            apply_theme(app, scale=action.data(), save=True)

        scale_group.triggered.connect(on_scale_selected)

    def _connect_run_flow(self, run_setup_vm: object, dashboard_vm: object) -> None:
        """Connect run setup to dashboard for run execution flow."""
        from lb_gui.views.run_setup_view import RunSetupView

        run_setup_view = self._views.get("run_setup")
        if not isinstance(run_setup_view, RunSetupView):
            return

        def on_start_run(request: object) -> None:
            """Handle run start request."""
            # Check if a run is already in progress
            if hasattr(self, "_current_worker") and self._current_worker is not None:
                if self._current_worker.is_running():  # type: ignore
                    QMessageBox.warning(
                        self,
                        "Error",
                        "A run is already in progress. Please wait for it to finish.",
                    )
                    return

            # Get the run plan for initializing dashboard
            try:
                plan = self.services.run_controller.get_run_plan(
                    request.config,  # type: ignore
                    list(request.tests),  # type: ignore
                    request.execution_mode,  # type: ignore
                )
            except Exception as e:
                QMessageBox.warning(
                    self,
                    "Error",
                    f"Failed to get run plan: {e}",
                )
                return

            # Create a minimal journal for initialization
            from lb_app.api import RunJournal

            journal: RunJournal = self.services.run_controller.build_journal(
                request.run_id  # type: ignore
            )

            # Initialize dashboard
            dashboard_vm.initialize(plan, journal)  # type: ignore

            # Switch to dashboard view
            self.select_section("dashboard")

            # Lock UI
            self._set_ui_busy(True)

            # Create and start worker
            worker = self.services.run_controller.create_worker(request)  # type: ignore

            # Connect worker signals to dashboard
            worker.signals.log_line.connect(dashboard_vm.on_log_line)  # type: ignore
            worker.signals.status_line.connect(dashboard_vm.on_status)  # type: ignore
            worker.signals.warning.connect(dashboard_vm.on_warning)  # type: ignore
            worker.signals.journal_update.connect(dashboard_vm.on_journal_update)  # type: ignore
            worker.signals.finished.connect(dashboard_vm.on_run_finished)  # type: ignore
            
            # Connect worker signals to main window for cleanup
            worker.signals.finished.connect(self._on_run_finished)  # type: ignore

            # Store worker reference to prevent garbage collection
            self._current_worker = worker
            worker.start()

        run_setup_view.start_run_requested.connect(on_start_run)

    def _set_ui_busy(self, busy: bool) -> None:
        """Enable or disable UI interaction during run."""
        self._sidebar.setEnabled(not busy)
        if busy:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        else:
            QApplication.restoreOverrideCursor()

    def _on_run_finished(self, success: bool, error: str) -> None:
        """Handle run completion to restore UI state."""
        self._set_ui_busy(False)
        self._current_worker = None
        
        if not success:
             QMessageBox.critical(
                self,
                "Run Failed",
                f"Benchmark run failed or completed with error:\n{error}",
            )

    def closeEvent(self, event: object) -> None:
        """Handle window close request."""
        # Use getattr to check existence safely
        worker = getattr(self, "_current_worker", None)
        if worker is not None and worker.is_running():  # type: ignore
            reply = QMessageBox.question(
                self,
                "Benchmark Running",
                "A benchmark is currently running. Closing the application may leave "
                "remote processes active.\n\nAre you sure you want to force quit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                event.ignore()  # type: ignore
                return
        
        event.accept()  # type: ignore

    def _connect_config_flow(
        self,
        config_vm: object,
        run_setup_vm: object,
        results_vm: object,
        analytics_vm: object,
    ) -> None:
        """Connect config changes to dependent views."""
        try:
            config_loaded = config_vm.config_loaded  # type: ignore[attr-defined]
        except Exception:
            return

        def on_config_loaded(_: object) -> None:
            self._sync_config_to_views(
                config_vm, run_setup_vm, results_vm, analytics_vm
            )

        config_loaded.connect(on_config_loaded)

    def _sync_config_to_views(
        self,
        config_vm: object,
        run_setup_vm: object,
        results_vm: object,
        analytics_vm: object,
    ) -> None:
        """Apply the loaded config to views that depend on it."""
        config_path = getattr(config_vm, "config_path", None)
        config_obj = getattr(config_vm, "config", None)

        if config_obj is not None and hasattr(run_setup_vm, "set_config"):
            run_setup_vm.set_config(config_obj)
            run_setup_vm.refresh_workloads()
        elif hasattr(run_setup_vm, "load_config"):
            run_setup_vm.load_config(config_path)
            run_setup_vm.refresh_workloads()

        if config_obj is not None and hasattr(results_vm, "configure_with_config"):
            results_vm.configure_with_config(config_obj)
            results_vm.refresh_runs()
        elif hasattr(results_vm, "configure"):
            if results_vm.configure(config_path):
                results_vm.refresh_runs()

        if config_obj is not None and hasattr(analytics_vm, "configure_with_config"):
            analytics_vm.configure_with_config(config_obj)
            analytics_vm.refresh_runs()
        elif hasattr(analytics_vm, "configure"):
            if analytics_vm.configure(config_path):
                analytics_vm.refresh_runs()

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
