"""Application setup and global services."""

from __future__ import annotations

from lb_gui.services.app_client import AppClientService
from lb_gui.services.config_service import GUIConfigService
from lb_gui.services.plugin_service import PluginService
from lb_gui.services.run_catalog import RunCatalogServiceWrapper
from lb_gui.services.analytics_service import AnalyticsServiceWrapper
from lb_gui.services.doctor_service import DoctorServiceWrapper
from lb_gui.services.run_controller import RunControllerService
from lb_gui.windows.main_window import MainWindow


class ServiceContainer:
    """Container for all GUI services (dependency injection)."""

    def __init__(self) -> None:
        self._app_client: AppClientService | None = None
        self._config_service: GUIConfigService | None = None
        self._plugin_service: PluginService | None = None
        self._run_catalog: RunCatalogServiceWrapper | None = None
        self._analytics_service: AnalyticsServiceWrapper | None = None
        self._doctor_service: DoctorServiceWrapper | None = None
        self._run_controller: RunControllerService | None = None

    @property
    def app_client(self) -> AppClientService:
        if self._app_client is None:
            self._app_client = AppClientService()
        return self._app_client

    @property
    def config_service(self) -> GUIConfigService:
        if self._config_service is None:
            self._config_service = GUIConfigService()
        return self._config_service

    @property
    def plugin_service(self) -> PluginService:
        if self._plugin_service is None:
            self._plugin_service = PluginService()
        return self._plugin_service

    @property
    def run_catalog(self) -> RunCatalogServiceWrapper:
        if self._run_catalog is None:
            self._run_catalog = RunCatalogServiceWrapper()
        return self._run_catalog

    @property
    def analytics_service(self) -> AnalyticsServiceWrapper:
        if self._analytics_service is None:
            self._analytics_service = AnalyticsServiceWrapper()
        return self._analytics_service

    @property
    def doctor_service(self) -> DoctorServiceWrapper:
        if self._doctor_service is None:
            self._doctor_service = DoctorServiceWrapper()
        return self._doctor_service

    @property
    def run_controller(self) -> RunControllerService:
        if self._run_controller is None:
            self._run_controller = RunControllerService(self.app_client)
        return self._run_controller


def create_app() -> MainWindow:
    """Create and wire up the main application window."""
    services = ServiceContainer()
    window = MainWindow(services)
    return window
