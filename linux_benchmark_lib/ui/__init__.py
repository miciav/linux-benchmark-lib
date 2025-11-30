"""
UI adapter package providing Textual-based and headless renderers.
"""

from .factory import get_ui_adapter
from .types import UIAdapter, ProgressHandle

__all__ = ["get_ui_adapter", "UIAdapter", "ProgressHandle"]
