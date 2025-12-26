from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple, Optional

from lb_app.api import (
    AnalyticsService,
    ApplicationClient,
    ConfigService,
    DoctorService,
    TestService,
    UIAdapter,
)
from lb_common.api import configure_logging
from lb_ui.tui.adapters.tui_adapter import TUIAdapter
from lb_ui.tui.system.facade import TUI
from lb_ui.tui.system.protocols import UI


@dataclass
class UIContext:
    """Container for UI services and state, initialized lazily."""
    headless: bool = False
    dev_mode: bool = False
    
    # Lazily initialized services
    _ui: Optional[UI] = None
    _ui_adapter: Optional[UIAdapter] = None
    _config_service: Optional[ConfigService] = None
    _doctor_service: Optional[DoctorService] = None
    _test_service: Optional[TestService] = None
    _analytics_service: Optional[AnalyticsService] = None
    _app_client: Optional[ApplicationClient] = None

    @property
    def ui(self) -> UI:
        if self._ui is None:
            if self.headless:
                from lb_ui.tui.system.headless import HeadlessUI
                self._ui = HeadlessUI()
            else:
                self._ui = TUI()
        return self._ui

    @ui.setter
    def ui(self, value: UI):
        self._ui = value

    @property
    def ui_adapter(self) -> UIAdapter:
        if self._ui_adapter is None:
            self._ui_adapter = TUIAdapter(self.ui)
        return self._ui_adapter

    @ui_adapter.setter
    def ui_adapter(self, value: UIAdapter):
        self._ui_adapter = value

    @property
    def config_service(self) -> ConfigService:
        if self._config_service is None:
            self._config_service = ConfigService()
        return self._config_service

    @config_service.setter
    def config_service(self, value: ConfigService):
        self._config_service = value

    @property
    def doctor_service(self) -> DoctorService:
        if self._doctor_service is None:
            self._doctor_service = DoctorService(config_service=self.config_service)
        return self._doctor_service

    @doctor_service.setter
    def doctor_service(self, value: DoctorService):
        self._doctor_service = value

    @property
    def test_service(self) -> TestService:
        if self._test_service is None:
            self._test_service = TestService()
        return self._test_service

    @test_service.setter
    def test_service(self, value: TestService):
        self._test_service = value

    @property
    def analytics_service(self) -> AnalyticsService:
        if self._analytics_service is None:
            self._analytics_service = AnalyticsService()
        return self._analytics_service

    @analytics_service.setter
    def analytics_service(self, value: AnalyticsService):
        self._analytics_service = value

    @property
    def app_client(self) -> ApplicationClient:
        if self._app_client is None:
            self._app_client = ApplicationClient()
        return self._app_client

    @app_client.setter
    def app_client(self, value: ApplicationClient):
        self._app_client = value


def load_dev_mode(cli_root: Path) -> bool:
    """Return True when dev mode is enabled via marker file or pyproject flag."""
    marker = cli_root / ".lb_dev_cli"
    if marker.exists():
        return True
    pyproject = cli_root / "pyproject.toml"
    if pyproject.exists():
        try:
            data = tomllib.loads(pyproject.read_text())
            tool_cfg = data.get("tool", {}).get("lb_ui", {}) or {}
            if isinstance(tool_cfg, dict):
                dev_flag = tool_cfg.get("dev_mode")
                if isinstance(dev_flag, bool):
                    return dev_flag
        except Exception:
            pass
    return False


__all__ = [
    "load_dev_mode",
    "UIContext",
    "configure_logging",
]
