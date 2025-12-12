"""
UI adapter package providing Textual-based and headless renderers.
"""

from lb_controller.ui_interfaces import UIAdapter, ProgressHandle  # re-export contract
from lb_ui.ui.adapters.console import ConsoleUIAdapter
from lb_ui.ui.adapters.headless import HeadlessUIAdapter
from lb_ui.ui.prompts import (
    prompt_analytics_kind,
    prompt_multi_select,
    prompt_multipass,
    prompt_plugins,
    prompt_remote_host,
    prompt_run_id,
)

__all__ = [
    "UIAdapter",
    "ProgressHandle",
    "ConsoleUIAdapter",
    "HeadlessUIAdapter",
    "prompt_plugins",
    "prompt_remote_host",
    "prompt_multipass",
    "prompt_run_id",
    "prompt_analytics_kind",
    "prompt_multi_select",
]
