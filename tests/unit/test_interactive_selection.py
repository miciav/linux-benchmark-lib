"""Tests for the TestService interactive logic."""

from unittest.mock import MagicMock, patch

from lb_controller.services.test_service import TestService


def test_select_multipass_interactive(monkeypatch):
    """Test interactive selection calls the Textual prompt and returns its value."""
    monkeypatch.setattr(
        "lb_controller.services.test_service.sys.stdin.isatty",
        lambda: True,
        raising=False,
    )

    with patch("lb_controller.services.test_service.prompt_multipass") as mock_prompt:
        mock_prompt.return_value = ("fio", "high")

        service = TestService()
        service.ui = MagicMock()

        scenario, level = service.select_multipass(False, default_level="medium")

        mock_prompt.assert_called_once()
        assert scenario == "fio"
        assert level == "high"


def test_select_multipass_non_interactive(monkeypatch):
    """Test fallback when not interactive."""
    monkeypatch.setattr(
        "lb_controller.services.test_service.sys.stdin.isatty",
        lambda: False,
        raising=False,
    )

    service = TestService()
    scenario, level = service.select_multipass(False, default_level="low")
    assert scenario == "stress_ng"
    assert level == "low"
