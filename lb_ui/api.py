"""Stable UI API surface."""

from __future__ import annotations

from typing import Any

import lb_ui.cli as _cli
from lb_ui.cli import app, ctx_store, main
from lb_ui.cli.commands import plugin as plugin_commands
from lb_ui.presenters.journal import build_journal_summary
from lb_ui.presenters.plan import build_run_plan_table
from lb_ui.tui.adapters.tui_adapter import TUIAdapter
from lb_ui.tui.system.components.dashboard import RichDashboard
from lb_ui.tui.system.headless import HeadlessUI
from lb_ui.tui.system.models import PickItem, SelectionNode


def __getattr__(name: str) -> Any:
    return getattr(_cli, name)


__all__ = [
    "HeadlessUI",
    "PickItem",
    "RichDashboard",
    "SelectionNode",
    "TUIAdapter",
    "app",
    "build_journal_summary",
    "build_run_plan_table",
    "ctx_store",
    "main",
    "plugin_commands",
    # Dynamic exports via __getattr__ forwarding to lb_ui.cli:
    # config_service, doctor_service, test_service, analytics_service,
    # app_client, ui, ui_adapter, DEV_MODE, subprocess
]
