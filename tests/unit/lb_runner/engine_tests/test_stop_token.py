"""Unit tests for StopToken."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from lb_runner.engine.stop_token import StopToken


pytestmark = [pytest.mark.unit, pytest.mark.unit_runner]


class TestStopTokenInit:
    """Tests for StopToken initialization."""

    def test_creates_without_signal_handlers(self) -> None:
        """StopToken can be created without signal handlers."""
        token = StopToken(enable_signals=False)
        assert token.should_stop() is False
        assert token.stop_file is None

    def test_creates_with_stop_file(self, tmp_path: Path) -> None:
        """StopToken can be configured with a stop file path."""
        stop_file = tmp_path / "stop"
        token = StopToken(stop_file=stop_file, enable_signals=False)
        assert token.stop_file == stop_file

    def test_creates_with_on_stop_callback(self) -> None:
        """StopToken accepts an on_stop callback."""
        callback = MagicMock()
        token = StopToken(enable_signals=False, on_stop=callback)
        assert token._on_stop is callback


class TestStopTokenRequestStop:
    """Tests for request_stop method."""

    def test_request_stop_sets_flag(self) -> None:
        """request_stop should set the stop flag."""
        token = StopToken(enable_signals=False)
        assert token.should_stop() is False

        token.request_stop()

        assert token.should_stop() is True

    def test_request_stop_calls_callback(self) -> None:
        """request_stop should call the on_stop callback."""
        callback = MagicMock()
        token = StopToken(enable_signals=False, on_stop=callback)

        token.request_stop()

        callback.assert_called_once()

    def test_request_stop_only_calls_callback_once(self) -> None:
        """request_stop should only call callback on first invocation."""
        callback = MagicMock()
        token = StopToken(enable_signals=False, on_stop=callback)

        token.request_stop()
        token.request_stop()
        token.request_stop()

        callback.assert_called_once()

    def test_request_stop_handles_callback_exception(self) -> None:
        """request_stop should not raise if callback fails."""
        callback = MagicMock(side_effect=RuntimeError("callback error"))
        token = StopToken(enable_signals=False, on_stop=callback)

        # Should not raise
        token.request_stop()

        assert token.should_stop() is True


class TestStopTokenShouldStop:
    """Tests for should_stop method."""

    def test_should_stop_returns_false_initially(self) -> None:
        """should_stop returns False when not stopped."""
        token = StopToken(enable_signals=False)
        assert token.should_stop() is False

    def test_should_stop_returns_true_after_request(self) -> None:
        """should_stop returns True after request_stop."""
        token = StopToken(enable_signals=False)
        token.request_stop()
        assert token.should_stop() is True

    def test_should_stop_detects_stop_file(self, tmp_path: Path) -> None:
        """should_stop returns True when stop file exists."""
        stop_file = tmp_path / "stop"
        token = StopToken(stop_file=stop_file, enable_signals=False)

        assert token.should_stop() is False

        stop_file.touch()

        assert token.should_stop() is True

    def test_stop_file_triggers_callback(self, tmp_path: Path) -> None:
        """Stop file detection should trigger callback."""
        callback = MagicMock()
        stop_file = tmp_path / "stop"
        token = StopToken(stop_file=stop_file, enable_signals=False, on_stop=callback)

        stop_file.touch()
        token.should_stop()

        callback.assert_called_once()

    def test_stop_file_callback_only_once(self, tmp_path: Path) -> None:
        """Stop file should only trigger callback once."""
        callback = MagicMock()
        stop_file = tmp_path / "stop"
        token = StopToken(stop_file=stop_file, enable_signals=False, on_stop=callback)

        stop_file.touch()
        token.should_stop()
        token.should_stop()
        token.should_stop()

        callback.assert_called_once()


class TestStopTokenContextManager:
    """Tests for context manager protocol."""

    def test_context_manager_returns_self(self) -> None:
        """__enter__ should return the token itself."""
        token = StopToken(enable_signals=False)
        with token as t:
            assert t is token

    def test_context_manager_calls_restore(self) -> None:
        """__exit__ should call restore."""
        token = StopToken(enable_signals=False)
        token.restore = MagicMock()

        with token:
            pass

        token.restore.assert_called_once()


class TestStopTokenRestore:
    """Tests for restore method."""

    def test_restore_clears_handlers(self) -> None:
        """restore should clear the prev_handlers dict."""
        token = StopToken(enable_signals=False)
        token._prev_handlers = {1: lambda: None, 2: lambda: None}

        token.restore()

        assert token._prev_handlers == {}
