from __future__ import annotations

from typing import Sequence

from lb_ui.tui.core.capabilities import is_tty_available
from lb_ui.tui.screens.picker_screen import PickerScreen
from lb_ui.tui.system.models import PickItem, SelectionNode
from lb_ui.tui.core.protocols import HierarchicalPicker, Picker


class PowerPicker(Picker):
    def pick_one(
        self,
        items: Sequence[PickItem],
        *,
        title: str,
        query_hint: str = "",
    ) -> PickItem | None:
        if not items:
            return None
        if not is_tty_available():
            return None
        screen = PickerScreen(
            title=title,
            items=items,
            multi_select=False,
            query_hint=query_hint,
        )
        return screen.run()

    def pick_many(
        self,
        items: Sequence[PickItem],
        *,
        title: str,
        query_hint: str = "",
    ) -> list[PickItem] | None:
        if not items:
            return None
        if not is_tty_available():
            return None
        screen = PickerScreen(
            title=title,
            items=items,
            multi_select=True,
            query_hint=query_hint,
        )
        return screen.run()


class PowerHierarchicalPicker(HierarchicalPicker):
    def pick_one(
        self,
        root: SelectionNode,
        *,
        title: str,
    ) -> SelectionNode | None:
        if not is_tty_available():
            return None
        screen = PickerScreen(title=title, root=root)
        return screen.run()
