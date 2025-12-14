from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Sequence

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout, HSplit, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import Frame
from prompt_toolkit.styles import Style

from lb_ui.ui.system.components.flat_picker_panel import FlatPickerPanel, FlatPickerPanelConfig
from lb_ui.ui.system.models import PickItem, SelectionNode
from lb_ui.ui.system.protocols import HierarchicalPicker


@dataclass
class PickerState:
    path: list[SelectionNode]
    current: SelectionNode
    filter: str = ""


class _HierarchicalPickerApp:
    def __init__(self, root: SelectionNode, title: str):
        self.state = PickerState(path=[root], current=root)
        self.title = title

        items, node_by_item_id = self._items_for_children(root.children)
        self._node_by_item_id: dict[str, SelectionNode] = node_by_item_id
        self._panel = FlatPickerPanel(
            items,
            row_renderer=self._render_row,
            config=FlatPickerPanelConfig(wrap_navigation=True),
        )
        self.search = self._panel.search
        self.list_control = self._panel.list_control
        self.preview_control = self._panel.preview_control

        self.kb = self._keybindings()

        # Inner layout
        inner_layout = HSplit(
            [
                Window(content=FormattedTextControl(self._render_path), height=1, style="class:path"),
                self.search,
                Window(height=1, char="-", style="class:separator"),
                VSplit(
                    [
                        Window(self.list_control),
                        Window(width=1, char="|", style="class:separator"),
                        Window(self.preview_control),
                    ],
                    padding=1,
                ),
            ]
        )

        root_container = Frame(inner_layout, title=title)

        self.app = Application(
            layout=Layout(root_container, focused_element=self.search),
            key_bindings=self.kb,
            style=Style.from_dict({
                "selected": "bg:#0000aa fg:white bold",
                "path": "fg:blue bold underline",
                "separator": "fg:#0000aa",
                "frame.border": "fg:#0000aa",
                "frame.label": "fg:#0000aa bold",
                "search": "bg:#eeeeee fg:#000000",
            }),
            full_screen=True,
        )

        self.search.buffer.on_text_changed += lambda _: self._apply_filter()

    def _items_for_children(
        self, children: Sequence[SelectionNode]
    ) -> tuple[list[PickItem], dict[str, SelectionNode]]:
        items: list[PickItem] = []
        node_by_item_id: dict[str, SelectionNode] = {}

        for child in children:
            node_by_item_id[child.id] = child
            child_count = len(child.children)
            desc_lines = [
                child.label,
                f"Kind: {child.kind}",
                f"ID: {child.id}",
            ]
            if child_count:
                desc_lines.append(f"Children: {child_count}")
            items.append(
                PickItem(
                    id=child.id,
                    title=child.label,
                    description="\n".join(desc_lines),
                    search_blob=f"{child.label} {child.kind} {child.id}",
                    preview=child.preview,
                    payload=child,
                )
            )

        return items, node_by_item_id

    def _apply_filter(self) -> None:
        self.state.filter = self.search.text.strip()
        self._panel.apply_filter(reset_index=True)
        self.app.invalidate()

    def _render_path(self) -> str:
        return "Path: " + " > ".join(n.label for n in self.state.path)

    def _render_row(self, item: PickItem, is_selected: bool) -> tuple[str, str]:
        node = self._node_by_item_id.get(item.id)
        has_children = bool(node and node.children)
        indicator = "▸" if has_children else "•"
        style = "class:selected" if is_selected else ""
        return style, f" {indicator} {item.title}"

    def _keybindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("down")
        def _(e) -> None:
            self._panel.move(1)
            self.app.invalidate()

        @kb.add("up")
        def _(e) -> None:
            self._panel.move(-1)
            self.app.invalidate()

        @kb.add("enter")
        def _(e) -> None:
            item = self._panel.selected_item
            if item is None:
                return
            node = self._node_by_item_id.get(item.id)
            if node is None:
                return
            if node.children:
                # Descend
                self.state.path.append(node)
                self.state.current = node
                self.state.filter = ""
                items, node_by_item_id = self._items_for_children(node.children)
                self._node_by_item_id = node_by_item_id
                self._panel.set_items(items, keep_filter=False)
            else:
                # Select leaf
                e.app.exit(result=node)

        @kb.add("backspace")
        @kb.add("left")
        def _(e) -> None:
            if len(self.state.path) > 1:
                # Go up
                self.state.path.pop()
                self.state.current = self.state.path[-1]
                self.state.filter = ""
                items, node_by_item_id = self._items_for_children(self.state.current.children)
                self._node_by_item_id = node_by_item_id
                self._panel.set_items(items, keep_filter=False)
                self.app.invalidate()
            elif self.state.filter:
                # At root: clear filter to allow refining again.
                self.state.filter = ""
                self._panel.reset_filter()
                self.app.invalidate()

        @kb.add("escape")
        def _(e) -> None:
            e.app.exit(result=None)

        @kb.add("c-r")
        def _(e) -> None:
            self.state.filter = ""
            self._panel.reset_filter()
            self.app.invalidate()

        @kb.add("c-c")
        def _(e) -> None:
            e.app.exit(result=None)

        return kb

    def run(self) -> SelectionNode | None:
        return self.app.run()


class PowerHierarchicalPicker(HierarchicalPicker):
    def pick_one(
        self,
        root: SelectionNode,
        *,
        title: str
    ) -> SelectionNode | None:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            return None
        app = _HierarchicalPickerApp(root, title)
        return app.run()
