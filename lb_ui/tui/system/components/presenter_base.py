"""Compatibility re-exports for presenter base types."""

from __future__ import annotations

from lb_ui.tui.system.protocols import Presenter, PresenterSink

PresenterBase = Presenter

__all__ = ["PresenterBase", "PresenterSink"]
