"""Compatibility re-export for the Dashboard base class."""

from __future__ import annotations

from lb_ui.tui.system.protocols import Dashboard

DashboardNoOp = Dashboard

__all__ = ["DashboardNoOp"]
