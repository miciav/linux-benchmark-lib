from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Tuple

from lb_app.api import ApplicationClient, DoctorService, TestService, UIAdapter
from lb_analytics.engine.service import AnalyticsService
from lb_common import configure_logging
from lb_controller.api import ConfigService
from lb_ui.tui.adapters.tui_adapter import TUIAdapter
from lb_ui.tui.system.facade import TUI
from lb_ui.tui.system.protocols import UI


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


def create_ui(headless: bool = False) -> Tuple[UI, UIAdapter]:
    """Create UI and adapter; headless UI can be supplied later if needed."""
    ui: UI = TUI()
    adapter: UIAdapter = TUIAdapter(ui)
    if headless:
        from lb_ui.tui.system.headless import HeadlessUI
        ui = HeadlessUI()
        adapter = TUIAdapter(ui)
    return ui, adapter


def create_services() -> tuple[ConfigService, DoctorService, TestService, AnalyticsService, ApplicationClient]:
    """Instantiate core services used by the CLI."""
    config_service = ConfigService()
    doctor_service = DoctorService(config_service=config_service)
    test_service = TestService()
    analytics_service = AnalyticsService()
    app_client = ApplicationClient()
    return config_service, doctor_service, test_service, analytics_service, app_client


__all__ = [
    "load_dev_mode",
    "create_ui",
    "create_services",
    "configure_logging",
]
