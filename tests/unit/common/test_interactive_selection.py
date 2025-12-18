"""Tests for the TestService interactive logic."""

import sys
from unittest.mock import MagicMock, patch

import pytest

from lb_controller.services.test_service import TestService
from lb_ui.ui import prompts as tui_prompts

pytestmark = [pytest.mark.ui, pytest.mark.ui]


def test_select_multipass_interactive(monkeypatch):
    """Test interactive selection calls the Textual prompt and returns its value."""
    mock_stdin = MagicMock()
    mock_stdin.isatty.return_value = True
    monkeypatch.setattr(sys, "stdin", mock_stdin)
    mock_stdout = MagicMock()
    mock_stdout.isatty.return_value = True
    monkeypatch.setattr(sys, "stdout", mock_stdout)

    class DummyPrompt:
        def __init__(self, value):
            self._value = value

        def execute(self):
            return self._value


    class DummyInquirer:
        def checkbox(self, **_kwargs):
            return DummyPrompt(["fio"])

        def select(self, **_kwargs):
            return DummyPrompt("high")

    monkeypatch.setattr(tui_prompts, "_check_tty", lambda: True)
    monkeypatch.setattr(tui_prompts, "_load_inquirer", lambda: DummyInquirer())

    with patch(
        "lb_controller.services.test_service.ConfigService"
    ) as mock_cfg_cls:
        mock_cfg = mock_cfg_cls.return_value
        mock_cfg.create_default_config.return_value.workloads = {
            "stress_ng": {},
            "dd": {},
            "fio": {},
        }

        service = TestService()
        service.ui = MagicMock()
        service.ui.prompt_multipass_scenario.return_value = ("fio", "high")

        scenario, level = service.select_multipass(False, default_level="medium")

        assert scenario == "fio"
        assert level == "high"


def test_select_multipass_non_interactive(monkeypatch):
    """Test fallback when not interactive."""
    mock_stdin = MagicMock()
    mock_stdin.isatty.return_value = False
    monkeypatch.setattr(sys, "stdin", mock_stdin)
    mock_stdout = MagicMock()
    mock_stdout.isatty.return_value = True
    monkeypatch.setattr(sys, "stdout", mock_stdout)

    with patch("lb_controller.services.test_service.ConfigService") as mock_cfg_cls:
        mock_cfg = mock_cfg_cls.return_value
        mock_cfg.create_default_config.return_value.workloads = {"stress_ng": {}}

        service = TestService()
        # Mock UI for non-interactive case too, though logic should bypass prompt
        service.ui = MagicMock()
        service.ui.prompt_multipass_scenario.return_value = None
        
        scenario, level = service.select_multipass(False, default_level="low")
        assert scenario == "stress_ng"
        assert level == "low"


def test_prompt_multipass_without_inquirer(monkeypatch):
    """Fallback to defaults when InquirerPy is missing."""

    class DummyUI:
        def __init__(self):
            self.warning = None

        def show_table(self, *_args, **_kwargs):
            return None

        def show_warning(self, message: str):
            self.warning = message

    ui = DummyUI()
    monkeypatch.setattr(tui_prompts, "_check_tty", lambda: True)
    monkeypatch.setattr(tui_prompts, "_load_inquirer", lambda: None)
    
    scenario, level = tui_prompts.prompt_multipass(
        ["stress_ng", "dd"],
        ui_adapter=ui,
        default_level="high",
    )

    assert scenario == "stress_ng"
    assert level == "high"
    assert ui.warning and "InquirerPy" in ui.warning
