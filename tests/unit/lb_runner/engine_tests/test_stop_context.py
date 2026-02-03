"""Tests for stop context helpers."""

from __future__ import annotations

import pytest

from lb_runner.engine.stop_context import (
    clear_stop_token,
    get_stop_token,
    should_stop,
    stop_context,
)
from lb_runner.engine.stop_token import StopToken


pytestmark = [pytest.mark.unit, pytest.mark.unit_runner]


def test_stop_context_sets_and_clears() -> None:
    token = StopToken(enable_signals=False)
    clear_stop_token()
    assert get_stop_token() is None
    with stop_context(token):
        assert get_stop_token() is token
    assert get_stop_token() is None


def test_should_stop_uses_explicit_token() -> None:
    token = StopToken(enable_signals=False)
    token.request_stop()
    clear_stop_token()
    assert should_stop(token) is True
    assert should_stop() is False


def test_stop_context_restores_previous() -> None:
    token_a = StopToken(enable_signals=False)
    token_b = StopToken(enable_signals=False)
    clear_stop_token()
    with stop_context(token_a):
        assert get_stop_token() is token_a
        with stop_context(token_b):
            assert get_stop_token() is token_b
        assert get_stop_token() is token_a
    assert get_stop_token() is None
