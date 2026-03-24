# tests/unit/lb_gui/test_qt_utils.py
"""Tests for Qt utility helpers."""
from __future__ import annotations
import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QColor


@pytest.mark.unit
def test_status_color_for_known_statuses():
    from lb_gui.utils.qt import status_color
    assert status_color("completed") == QColor("#22c55e")
    assert status_color("running") == QColor("#2dd4bf")
    assert status_color("failed") == QColor("#ef4444")


@pytest.mark.unit
def test_status_color_returns_none_for_unknown():
    from lb_gui.utils.qt import status_color
    assert status_color("pending") is None
    assert status_color("") is None
