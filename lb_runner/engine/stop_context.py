"""Context-scoped accessors for StopToken."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Generator

from lb_runner.engine.stop_token import StopToken

_STOP_TOKEN: ContextVar[StopToken | None] = ContextVar("lb_stop_token", default=None)


def set_stop_token(token: StopToken | None) -> Token:
    """Bind a stop token to the current context."""
    return _STOP_TOKEN.set(token)


def clear_stop_token(previous: Token | None = None) -> None:
    """Clear the current stop token or restore a previous context value."""
    if previous is not None:
        _STOP_TOKEN.reset(previous)
        return
    _STOP_TOKEN.set(None)


def get_stop_token(explicit: StopToken | None = None) -> StopToken | None:
    """Return the explicit token or the context-scoped token."""
    if explicit is not None:
        return explicit
    return _STOP_TOKEN.get()


def should_stop(explicit: StopToken | None = None) -> bool:
    """Return True if the active stop token is tripped."""
    token = get_stop_token(explicit)
    return bool(token and token.should_stop())


@contextmanager
def stop_context(token: StopToken | None) -> Generator[None, None, None]:
    """Context manager that binds a stop token for the current scope."""
    previous = set_stop_token(token)
    try:
        yield
    finally:
        clear_stop_token(previous)
