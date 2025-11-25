"""Tests for the TestService interactive logic."""

from unittest.mock import MagicMock, patch

from services.test_service import TestService


@patch("services.test_service.prompt_multipass")
@patch("services.test_service.sys.stdin.isatty", return_value=True)
def test_select_multipass_interactive(mock_isatty, mock_prompt):
    """Test interactive selection calls the Textual prompt and returns its value."""
    mock_prompt.return_value = ("fio", "high")

    service = TestService()
    service.ui = MagicMock()

    scenario, level = service.select_multipass(False, False, default_level="medium")

    mock_prompt.assert_called_once()
    assert scenario == "fio"
    assert level == "high"


@patch("services.test_service.sys.stdin.isatty", return_value=False)
def test_select_multipass_non_interactive(mock_isatty):
    """Test fallback when not interactive."""
    service = TestService()
    scenario, level = service.select_multipass(False, False, default_level="low")
    assert scenario == "stress_ng"
    assert level == "low"
