"""Tests for prompt fallbacks and validation."""

import sys
from types import SimpleNamespace

import pytest

from lb_ui.ui import prompts


pytestmark = pytest.mark.unit


def test_prompt_plugins_non_tty_returns_none(monkeypatch):
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: False))
    monkeypatch.setattr(sys, "stdout", SimpleNamespace(isatty=lambda: False))
    assert prompts.prompt_plugins({}, {}) is None


def test_prompt_multipass_fallback(monkeypatch):
    monkeypatch.setattr(prompts, "_check_tty", lambda: True)
    monkeypatch.setattr(prompts, "_load_inquirer", lambda: None)

    class DummyUI:
        def __init__(self):
            self.warning = None

        def show_table(self, *_args, **_kwargs):
            return None

        def show_warning(self, msg: str):
            self.warning = msg

    ui = DummyUI()
    scenario, level = prompts.prompt_multipass(["stress_ng", "dd"], ui_adapter=ui, default_level="medium")
    assert scenario == "stress_ng"
    assert level == "medium"
