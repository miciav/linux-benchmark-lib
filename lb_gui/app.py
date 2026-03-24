"""Application setup and global services."""

from __future__ import annotations

from functools import cached_property

from lb_gui.services.app_client import AppClientService
from lb_gui.services.config_service import GUIConfigService
from lb_gui.services.plugin_service import PluginService
from lb_gui.services.run_catalog import RunCatalogServiceWrapper
from lb_gui.services.analytics_service import AnalyticsServiceWrapper
from lb_gui.services.doctor_service import DoctorServiceWrapper
from lb_gui.services.run_controller import RunControllerService
from lb_gui.windows.main_window import MainWindow


class ServiceContainer:
    """Container for all GUI services (lazy dependency injection)."""

    @cached_property
    def app_client(self) -> AppClientService:
        return AppClientService()

    @cached_property
    def config_service(self) -> GUIConfigService:
        return GUIConfigService()

    @cached_property
    def plugin_service(self) -> PluginService:
        return PluginService()

    @cached_property
    def run_catalog(self) -> RunCatalogServiceWrapper:
        return RunCatalogServiceWrapper()

    @cached_property
    def analytics_service(self) -> AnalyticsServiceWrapper:
        return AnalyticsServiceWrapper()

    @cached_property
    def doctor_service(self) -> DoctorServiceWrapper:
        return DoctorServiceWrapper()

    @cached_property
    def run_controller(self) -> RunControllerService:
        return RunControllerService(self.app_client)


def create_app() -> MainWindow:
    """Create and wire up the main application window."""
    services = ServiceContainer()
    window = MainWindow(services)
    return window
