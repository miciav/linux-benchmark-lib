from types import SimpleNamespace

import pytest

from lb_ui.tui.core import capabilities

pytestmark = pytest.mark.unit_ui


def test_is_tty_available_checks_stdio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        capabilities,
        "sys",
        SimpleNamespace(
            stdin=SimpleNamespace(isatty=lambda: True),
            stdout=SimpleNamespace(isatty=lambda: False),
        ),
    )
    assert capabilities.is_tty_available() is False


def test_fuzzy_matcher_none_when_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(capabilities, "_HAS_RAPIDFUZZ", False)
    assert capabilities.has_fuzzy_search() is False
    assert capabilities.fuzzy_matcher() is None
