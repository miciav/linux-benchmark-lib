from __future__ import annotations

import os
import sys
from typing import Optional

from .console_adapter import ConsoleUIAdapter
from .headless import HeadlessUIAdapter
from .types import UIAdapter


def get_ui_adapter(force_headless: Optional[bool] = None) -> UIAdapter:
    """
    Return a UI adapter based on environment and TTY availability.

    Headless mode is selected when LB_HEADLESS_UI=1, when force_headless=True,
    or when stdout is not a TTY.
    """
    env_headless = os.environ.get("LB_HEADLESS_UI") == "1"
    headless = force_headless if force_headless is not None else env_headless or not sys.stdout.isatty()
    if headless:
        return HeadlessUIAdapter()
    return ConsoleUIAdapter()
