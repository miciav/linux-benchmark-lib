"""Tests for the TestService interactive logic."""

import sys
from unittest.mock import MagicMock, patch

import pytest

from lb_app.services.test_service import TestService

pytestmark = [pytest.mark.ui, pytest.mark.ui]


def test_select_multipass_interactive(monkeypatch):
    """Test interactive selection calls the Textual prompt and returns its value."""
    mock_stdin = MagicMock()
    mock_stdin.isatty.return_value = True
    monkeypatch.setattr(sys, "stdin", mock_stdin)
    mock_stdout = MagicMock()
    mock_stdout.isatty.return_value = True
    monkeypatch.setattr(sys, "stdout", mock_stdout)

    with patch(
        "lb_app.services.test_service.ConfigService"
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

    with patch("lb_app.services.test_service.ConfigService") as mock_cfg_cls:
        mock_cfg = mock_cfg_cls.return_value
        mock_cfg.create_default_config.return_value.workloads = {"stress_ng": {}}

        service = TestService()
        # Mock UI for non-interactive case too, though logic should bypass prompt
        service.ui = MagicMock()
        service.ui.prompt_multipass_scenario.return_value = None
        
        scenario, level = service.select_multipass(False, default_level="low")
        assert scenario == "stress_ng"
        assert level == "low"


def test_select_multipass_prompt_none(monkeypatch):
    """Fallback to defaults when the UI returns no selection."""
    mock_stdin = MagicMock()
    mock_stdin.isatty.return_value = True
    monkeypatch.setattr(sys, "stdin", mock_stdin)
    mock_stdout = MagicMock()
    mock_stdout.isatty.return_value = True
    monkeypatch.setattr(sys, "stdout", mock_stdout)

    with patch("lb_app.services.test_service.ConfigService") as mock_cfg_cls:
        mock_cfg = mock_cfg_cls.return_value
        mock_cfg.create_default_config.return_value.workloads = {"stress_ng": {}, "fio": {}}

        service = TestService()
        service.ui = MagicMock()
        service.ui.prompt_multipass_scenario.return_value = None

        scenario, level = service.select_multipass(False, default_level="high")
        assert scenario == "stress_ng"
        assert level == "high"
