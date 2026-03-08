from __future__ import annotations

import importlib
from pathlib import Path
import sys

import pytest

pytestmark = pytest.mark.unit_controller


def _reload_lb_events() -> object:
    module_name = "lb_controller.ansible.callback_plugins.lb_events"
    module = sys.modules.get(module_name)
    if module is None:
        module = importlib.import_module(module_name)
    return importlib.reload(module)


def test_callback_debug_is_disabled_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("LB_EVENT_DEBUG", raising=False)
    monkeypatch.setenv("LB_EVENT_LOG_PATH", str(tmp_path / "events.jsonl"))
    module = _reload_lb_events()

    callback = module.CallbackModule()

    assert callback._debug is False
    assert not (tmp_path / "lb_events.debug.log").exists()


def test_callback_debug_log_is_opt_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LB_EVENT_DEBUG", "true")
    monkeypatch.setenv("LB_EVENT_LOG_PATH", str(tmp_path / "events.jsonl"))
    module = _reload_lb_events()

    callback = module.CallbackModule()

    debug_path = tmp_path / "lb_events.debug.log"
    assert callback._debug is True
    assert debug_path.exists()
    assert "Callback plugin initialized" in debug_path.read_text()
