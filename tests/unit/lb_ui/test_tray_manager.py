"""Tests for the tray manager service."""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

# Importing lb_ui.services.tray pulls in pystray, whose Xorg backend resolves
# the X display at import time and raises Xlib.error.DisplayNameError when there
# is none. That aborts collection for the entire pytest session rather than
# failing a single test, so skip the module before the import runs.
# CI provides a display via xvfb-run, so the tests do run there.
if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
    pytest.skip("tray tests require an X or Wayland display", allow_module_level=True)

from lb_ui.services import tray


def test_tray_manager_start_spawns_process(monkeypatch) -> None:
    manager = tray.TrayManager()
    process = MagicMock()
    ctx = MagicMock()
    ctx.Process.return_value = process

    def fake_get_context(method: str):
        assert method == "spawn"
        return ctx

    monkeypatch.setattr(tray, "pystray", object())
    monkeypatch.setattr(tray.multiprocessing, "get_context", fake_get_context)

    manager.start()

    ctx.Process.assert_called_once()
    kwargs = ctx.Process.call_args.kwargs
    assert kwargs["target"] is tray._run_tray_icon
    assert kwargs["daemon"] is True
    process.start.assert_called_once()


def test_tray_manager_stop_terminates_process() -> None:
    manager = tray.TrayManager()
    process = MagicMock()
    process.is_alive.side_effect = [True, False]
    manager._process = process

    manager.stop()

    process.terminate.assert_called_once()
    process.join.assert_called_once_with(timeout=1)
    process.kill.assert_not_called()
