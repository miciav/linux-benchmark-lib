from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.containers import AnyContainer, DynamicContainer
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Frame

from lb_ui.tui.system.components.flat_picker_panel import (
    FlatPickerPanel,
    FlatPickerPanelConfig,
)
from lb_ui.tui.system.models import PickItem, SelectionNode
from lb_ui.tui.core import theme


@dataclass
class PickerSelectionState:
    items: list[PickItem]
    selections: dict[int, int | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._index_by_objid = {id(item): idx for idx, item in enumerate(self.items)}

    def seed_from_items(self) -> None:
        for idx, item in enumerate(self.items):
            if item.disabled:
                continue
            if item.variants:
                selected_idx = _selected_variant_index(item.variants)
                if selected_idx is None and item.selected:
                    selected_idx = _default_variant_index(item.variants)
                if selected_idx is not None:
                    self.selections[idx] = selected_idx
            elif item.selected:
                self.selections[idx] = None

    def is_selected(self, item: PickItem) -> bool:
        idx = self._index_by_objid.get(id(item))
        return idx is not None and idx in self.selections

    def selected_variant_index(self, item: PickItem) -> int | None:
        idx = self._index_by_objid.get(id(item))
        if idx is None:
            return None
        return self.selections.get(idx)

    def selected_variant_title(self, item: PickItem) -> str:
        idx = self.selected_variant_index(item)
        if idx is None or idx >= len(item.variants):
            return ""
        return item.variants[idx].title

    def toggle_item(self, item: PickItem) -> None:
        if item.disabled:
            return
        idx = self._index_by_objid.get(id(item))
        if idx is None:
            return
        if idx in self.selections:
            del self.selections[idx]
            return
        if item.variants:
            default_idx = _default_variant_index(item.variants)
            if default_idx is None:
                return
            self.selections[idx] = default_idx
        else:
            self.selections[idx] = None

    def select_variant(self, item: PickItem, variant_index: int) -> None:
        if item.disabled:
            return
        idx = self._index_by_objid.get(id(item))
        if idx is None:
            return
        if variant_index < 0 or variant_index >= len(item.variants):
            return
        if item.variants[variant_index].disabled:
            return
        self.selections[idx] = variant_index

    def build_result(self, item: PickItem) -> PickItem:
        idx = self._index_by_objid.get(id(item))
        if idx is None:
            return item
        variant_idx = self.selections.get(idx)
        if variant_idx is not None and variant_idx < len(item.variants):
            return item.variants[variant_idx]
        return item

    def build_multi_result(self) -> list[PickItem]:
        return [
            self.build_result(self.items[idx]) for idx in sorted(self.selections.keys())
        ]


@dataclass
class HierarchyState:
    root: SelectionNode
    path: list[SelectionNode] = field(init=False)
    current: SelectionNode = field(init=False)
    items: list[PickItem] = field(init=False)
    node_by_item_id: dict[str, SelectionNode] = field(init=False)

    def __post_init__(self) -> None:
        self.path = [self.root]
        self.current = self.root
        self._refresh_items()

    def breadcrumb(self) -> str:
        return " > ".join(node.label for node in self.path)

    def descend(self, node: SelectionNode) -> bool:
        if not node.children:
            return False
        self.path.append(node)
        self.current = node
        self._refresh_items()
        return True

    def ascend(self) -> bool:
        if len(self.path) <= 1:
            return False
        self.path.pop()
        self.current = self.path[-1]
        self._refresh_items()
        return True

    def _refresh_items(self) -> None:
        self.items, self.node_by_item_id = _items_for_children(self.current.children)


class PickerScreen:
    def __init__(
        self,
        *,
        title: str,
        items: Sequence[PickItem] | None = None,
        root: SelectionNode | None = None,
        multi_select: bool = False,
        query_hint: str = "",
    ) -> None:
        if items is None and root is None:
            raise ValueError("PickerScreen requires items or root.")
        if items is not None and root is not None:
            raise ValueError("PickerScreen accepts either items or root, not both.")

        self._title = title
        self._multi_select = multi_select
        self._hierarchy: HierarchyState | None = None
        self._selection: PickerSelectionState | None = None
        self._show_variants = False
        self._variant_index = 0

        if root is not None:
            self._hierarchy = HierarchyState(root)
            panel_items = self._hierarchy.items
            panel_config = FlatPickerPanelConfig(wrap_navigation=True)
        else:
            panel_items = list(items or [])
            panel_config = FlatPickerPanelConfig()
            if multi_select:
                self._selection = PickerSelectionState(panel_items)
                self._selection.seed_from_items()

        self._panel = FlatPickerPanel(
            panel_items,
            row_renderer=self._render_row,
            config=panel_config,
        )
        if query_hint:
            self._panel.search.text = query_hint
            self._panel.apply_filter(reset_index=True)

        self.search = self._panel.search
        self.list_control = self._panel.list_control
        self.preview_control = self._panel.preview_control
        self.variants_control = FormattedTextControl(
            self._render_variants, focusable=True
        )

        self._path_control = FormattedTextControl(self._render_path)
        self._kb = self._bindings()

        def right_pane() -> AnyContainer:
            if self._show_variants:
                return Window(self.variants_control)
            return Window(self.preview_control)

        inner_layout = HSplit(
            [
                (
                    Window(
                        content=self._path_control,
                        height=1,
                        style="class:path",
                    )
                    if self._hierarchy
                    else Window(height=0)
                ),
                self.search,
                Window(height=1, char="-", style="class:separator"),
                VSplit(
                    [
                        Window(self.list_control, width=Dimension(weight=1)),
                        Window(width=1, char="|", style="class:separator"),
                        DynamicContainer(right_pane),
                    ],
                    padding=1,
                ),
            ]
        )

        root_container = Frame(inner_layout, title=title)
        self._app = Application(
            layout=Layout(root_container, focused_element=self.search),
            key_bindings=self._kb,
            style=_picker_style(),
            full_screen=True,
        )

        self.search.buffer.on_text_changed += lambda _: self._on_query_changed()

    def run(self) -> Any:
        return self._app.run()

    def _on_query_changed(self) -> None:
        self._panel.apply_filter(reset_index=True)
        self._app.invalidate()

    def _current_item(self) -> PickItem | None:
        return self._panel.selected_item

    def _render_path(self) -> str:
        if not self._hierarchy:
            return ""
        return f"Path: {self._hierarchy.breadcrumb()}"

    def _render_row(self, item: PickItem, is_selected: bool) -> tuple[str, str]:
        if self._hierarchy:
            node = self._hierarchy.node_by_item_id.get(item.id)
            indicator = "▸" if node and node.children else "•"
            style = "class:selected" if is_selected else ""
            return style, f" {indicator} {item.title}"

        style = "class:selected" if is_selected else ""
        if item.disabled and not is_selected:
            style = "class:disabled"

        if not self._multi_select:
            return style, f"   {item.title}"

        prefix = "[ ]"
        suffix = ""
        if item.disabled:
            prefix = "[!]"
        if self._selection and self._selection.is_selected(item):
            prefix = "[x]"
            if item.variants:
                variant_label = self._selection.selected_variant_title(item)
                if variant_label:
                    suffix = f" [{variant_label}]"
        if self._selection and self._selection.is_selected(item) and not is_selected:
            style = "class:checked"
        return style, f" {prefix} {item.title}{suffix}"

    def _render_variants(self) -> list[tuple[str, str]]:
        item = self._current_item()
        if not item or not item.variants:
            return [("", "No options available")]
        fragments: list[tuple[str, str]] = []
        fragments.append(("class:title", f"Select Option for {item.title}:\n\n"))
        for idx, variant in enumerate(item.variants):
            style = ""
            if idx == self._variant_index:
                style = "class:variant-selected"
            if variant.disabled:
                style = "class:disabled"
            fragments.append((style, f" > {variant.title}\n"))
        return fragments

    def _bindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("down")
        def _(event: Any) -> None:
            if self._show_variants:
                self._move_variant(1)
            else:
                self._move(1)

        @kb.add("up")
        def _(event: Any) -> None:
            if self._show_variants:
                self._move_variant(-1)
            else:
                self._move(-1)

        @kb.add("enter")
        def _(event: Any) -> None:
            if self._show_variants:
                self._confirm_variant()
                return
            if self._hierarchy:
                self._enter_hierarchy()
                return
            if self._multi_select:
                result = self._selection.build_multi_result() if self._selection else []
                self._exit(result)
                return
            current = self._current_item()
            if current is None:
                return
            if current.variants:
                self._open_variants()
            else:
                self._exit(current)

        @kb.add("right")
        def _(event: Any) -> None:
            if self._hierarchy or self._show_variants:
                return
            current = self._current_item()
            if current and current.variants:
                self._open_variants()

        @kb.add("left")
        @kb.add("backspace")
        def _(event: Any) -> None:
            if self._show_variants:
                self._close_variants()
                return
            if self._hierarchy:
                if self._hierarchy.ascend():
                    self._panel.set_items(self._hierarchy.items, keep_filter=False)
                    self._app.invalidate()
                elif self._panel.filter_text:
                    self._panel.reset_filter()
                    self._app.invalidate()

        @kb.add("space")
        def _(event: Any) -> None:
            if self._hierarchy or self._show_variants or not self._multi_select:
                return
            current = self._current_item()
            if current and self._selection:
                self._selection.toggle_item(current)
                self._app.invalidate()

        @kb.add("escape")
        def _(event: Any) -> None:
            if self._show_variants:
                self._close_variants()
                return
            self._exit(None)

        @kb.add("c-r")
        def _(event: Any) -> None:
            if self._show_variants:
                self._close_variants()
            self._panel.reset_filter()
            self._app.invalidate()

        @kb.add("c-c")
        def _(event: Any) -> None:
            self._exit(None)

        return kb

    def _enter_hierarchy(self) -> None:
        current = self._current_item()
        if current is None or not self._hierarchy:
            return
        node = self._hierarchy.node_by_item_id.get(current.id)
        if node is None:
            return
        if node.children:
            if self._hierarchy.descend(node):
                self._panel.set_items(self._hierarchy.items, keep_filter=False)
                self._app.invalidate()
        else:
            self._exit(node)

    def _open_variants(self) -> None:
        self._show_variants = True
        self._variant_index = 0
        self._app.layout.focus(self.variants_control)
        self._app.invalidate()

    def _close_variants(self) -> None:
        self._show_variants = False
        self._app.layout.focus(self.search)
        self._app.invalidate()

    def _move(self, delta: int) -> None:
        self._panel.move(delta)
        self._app.invalidate()

    def _move_variant(self, delta: int) -> None:
        current = self._current_item()
        if not current or not current.variants:
            return
        self._variant_index = max(
            0,
            min(self._variant_index + delta, len(current.variants) - 1),
        )
        self._app.invalidate()

    def _confirm_variant(self) -> None:
        current = self._current_item()
        if not current or not current.variants:
            return
        idx = max(0, min(self._variant_index, len(current.variants) - 1))
        if self._multi_select and self._selection:
            self._selection.select_variant(current, idx)
            self._close_variants()
            return
        self._exit(current.variants[idx])

    def _exit(self, result: Any) -> None:
        try:
            self._app.exit(result=result)
        except Exception as exc:  # pragma: no cover - defensive
            if "Return value already set" not in str(exc):
                raise


def _selected_variant_index(variants: Sequence[PickItem]) -> int | None:
    for idx, variant in enumerate(variants):
        if variant.disabled:
            continue
        if variant.selected:
            return idx
    return None


def _default_variant_index(variants: Sequence[PickItem]) -> int | None:
    for idx, variant in enumerate(variants):
        if variant.disabled:
            continue
        tail = variant.id.split(":", 1)[-1].lower()
        if variant.title.lower() == "medium" or tail == "medium":
            return idx
    for idx, variant in enumerate(variants):
        if not variant.disabled:
            return idx
    return 0 if variants else None


def _items_for_children(
    children: Iterable[SelectionNode],
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


def _picker_style() -> Style:
    return Style.from_dict(theme.prompt_toolkit_picker_style())
