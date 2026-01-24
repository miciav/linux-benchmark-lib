"""Theme management for the GUI."""

from __future__ import annotations

import os
from typing import Final

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from lb_gui.resources import resource_path

THEMES: Final[dict[str, str]] = {
    "warm": "theme_warm.qss",
    "dark": "theme_dark.qss",
    "graphite_teal": "theme_graphite_teal.qss",
}

_THEME_KEY: Final[str] = "ui/theme"
_SCALE_KEY: Final[str] = "ui/scale"

_BASE_FONT_SIZE: Final[int] = 13
_TITLE_FONT_SIZE: Final[int] = 18
_LOG_FONT_SIZE: Final[int] = 12
_BUTTON_MIN_HEIGHT: Final[int] = 26
_PADDING_Y: Final[int] = 6
_PADDING_X: Final[int] = 8
_BUTTON_PADDING_X: Final[int] = 12
_GROUP_MARGIN_TOP: Final[int] = 14
_GROUP_PADDING: Final[int] = 10
_HEADER_PADDING_Y: Final[int] = 6
_HEADER_PADDING_X: Final[int] = 8
_TABLE_ITEM_PADDING: Final[int] = 6
_LIST_ITEM_PADDING_Y: Final[int] = 6
_LIST_ITEM_PADDING_X: Final[int] = 8


def list_themes() -> list[str]:
    """Return available theme names."""
    return list(THEMES.keys())


def get_preferred_theme() -> str:
    """Resolve theme from explicit setting, env, or saved preference."""
    env_value = os.environ.get("LB_GUI_THEME")
    if env_value in THEMES:
        return env_value
    saved = _load_theme_preference()
    if saved in THEMES:
        return saved
    return "warm"


def get_preferred_scale() -> float:
    """Resolve UI scale from env or saved preference."""
    env_value = os.environ.get("LB_GUI_SCALE")
    if env_value:
        try:
            scale = float(env_value)
            if 0.8 <= scale <= 1.8:
                return scale
        except ValueError:
            pass
    saved = _load_scale_preference()
    if saved is not None:
        return saved
    return 1.0


def apply_theme(
    app: QApplication,
    name: str | None = None,
    scale: float | None = None,
    *,
    save: bool = False,
) -> str:
    """Apply a theme and optional UI scale. Returns the applied theme name."""
    selected = name or get_preferred_theme()
    if selected not in THEMES:
        selected = "warm"
    selected_scale = scale if scale is not None else get_preferred_scale()
    selected_scale = _clamp_scale(selected_scale)

    path = resource_path(THEMES[selected])
    if path.exists():
        qss = path.read_text(encoding="utf-8")
        if selected_scale != 1.0:
            qss = f"{qss}\n{_scale_overrides(selected_scale)}"
        app.setStyleSheet(qss)

    if save:
        _save_theme_preference(selected)
        _save_scale_preference(selected_scale)

    return selected


def _load_theme_preference() -> str | None:
    settings = QSettings()
    value = settings.value(_THEME_KEY)
    return value if isinstance(value, str) else None


def _save_theme_preference(name: str) -> None:
    settings = QSettings()
    settings.setValue(_THEME_KEY, name)


def _load_scale_preference() -> float | None:
    settings = QSettings()
    value = settings.value(_SCALE_KEY)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _save_scale_preference(scale: float) -> None:
    settings = QSettings()
    settings.setValue(_SCALE_KEY, float(scale))


def _clamp_scale(scale: float) -> float:
    if scale < 0.8:
        return 0.8
    if scale > 1.8:
        return 1.8
    return scale


def _scale_value(value: int, scale: float) -> int:
    return max(1, int(round(value * scale)))


def _scale_overrides(scale: float) -> str:
    base = _scale_value(_BASE_FONT_SIZE, scale)
    title = _scale_value(_TITLE_FONT_SIZE, scale)
    log = _scale_value(_LOG_FONT_SIZE, scale)
    btn_min = _scale_value(_BUTTON_MIN_HEIGHT, scale)
    pad_y = _scale_value(_PADDING_Y, scale)
    pad_x = _scale_value(_PADDING_X, scale)
    btn_pad_x = _scale_value(_BUTTON_PADDING_X, scale)
    group_margin = _scale_value(_GROUP_MARGIN_TOP, scale)
    group_pad = _scale_value(_GROUP_PADDING, scale)
    header_pad_y = _scale_value(_HEADER_PADDING_Y, scale)
    header_pad_x = _scale_value(_HEADER_PADDING_X, scale)
    table_pad = _scale_value(_TABLE_ITEM_PADDING, scale)
    list_pad_y = _scale_value(_LIST_ITEM_PADDING_Y, scale)
    list_pad_x = _scale_value(_LIST_ITEM_PADDING_X, scale)

    return f"""
QWidget {{
    font-size: {base}px;
}}
QLabel[role="title"] {{
    font-size: {title}px;
}}
QPlainTextEdit#logViewer {{
    font-size: {log}px;
}}
QPushButton {{
    min-height: {btn_min}px;
    padding: {pad_y}px {btn_pad_x}px;
}}
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    padding: {pad_y}px {pad_x}px;
}}
QGroupBox {{
    margin-top: {group_margin}px;
    padding: {group_pad}px;
}}
QHeaderView::section {{
    padding: {header_pad_y}px {header_pad_x}px;
}}
QTableView::item {{
    padding: {table_pad}px;
}}
QListWidget::item {{
    padding: {list_pad_y}px {list_pad_x}px;
}}
"""


__all__ = [
    "THEMES",
    "list_themes",
    "get_preferred_theme",
    "get_preferred_scale",
    "apply_theme",
]
