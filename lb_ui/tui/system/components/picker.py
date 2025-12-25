from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any, Sequence

from prompt_toolkit.application import Application
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout, HSplit, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import Frame
from prompt_toolkit.widgets import TextArea
from prompt_toolkit.styles import Style
from prompt_toolkit.layout.containers import DynamicContainer, AnyContainer
from prompt_toolkit.layout.dimension import Dimension
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from lb_ui.tui.system.components.flat_picker_panel import FlatPickerPanel
from lb_ui.tui.system.models import PickItem
from lb_ui.tui.system.protocols import Picker

try:
    from rapidfuzz import fuzz, process

    _HAS_RAPIDFUZZ = True
except Exception:  # pragma: no cover - optional dependency
    _HAS_RAPIDFUZZ = False


@dataclass
class _Node:
    id: str
    label: str
    kind: str
    tags: tuple[str, ...] = ()
    description: str = ""
    children: list["_Node"] = field(default_factory=list)
    payload: PickItem | None = None
    parent_id: str | None = None

    def search_blob(self) -> str:
        parts = [self.label, self.kind, " ".join(self.tags), self.description]
        return " ".join([p for p in parts if p]).strip()


@dataclass
class _PickerState:
    path: list[_Node]
    cursor: int = 0
    query: str = ""


class _TwoLevelPicker:
    """Two-level picker with per-level search and a single preview panel."""

    def __init__(self, root: _Node, *, title: str, query_hint: str = "") -> None:
        self.state = _PickerState(path=[root], cursor=0, query=query_hint)
        self.title = title
        self.rich = Console(force_terminal=True, color_system="truecolor")

        self.search = TextArea(height=1, prompt="Search: ", multiline=False)
        if query_hint:
            self.search.text = query_hint

        self.list_control = FormattedTextControl(self._list_fragments, focusable=True)
        self.preview_control = FormattedTextControl(self._preview_ansi)
        self.kb = self._bindings()

        root_container = HSplit(
            [
                Window(height=1, content=FormattedTextControl(self._header)),
                Window(height=1, content=FormattedTextControl(self._breadcrumb)),
                self.search,
                Window(height=1, char="-", style="class:separator"),
                VSplit(
                    [
                        Window(self.list_control, width=Dimension(weight=1)),
                        Window(width=1, char="|", style="class:separator"),
                        Window(self.preview_control, width=Dimension(weight=1)),
                    ],
                    padding=1,
                ),
            ]
        )

        self.app = Application(
            layout=Layout(root_container, focused_element=self.search),
            key_bindings=self.kb,
            style=Style.from_dict(
                {
                    "header": "bold",
                    "row.selected": "reverse",
                    "separator": "fg:#0000aa",
                    "search": "bg:#eeeeee fg:#000000",
                }
            ),
            full_screen=True,
        )

        self.search.buffer.on_text_changed += lambda _: self._on_query_changed()

    def _current(self) -> _Node:
        return self.state.path[-1]

    def _filter(self, children: list[_Node]) -> list[_Node]:
        query = self.state.query.strip()
        if not query:
            return children
        if _HAS_RAPIDFUZZ:
            matches = process.extract(
                query,
                [(c.search_blob(), c) for c in children],
                scorer=fuzz.WRatio,
            )
            return [m[0][1] for m in matches]
        lower = query.lower()
        return [c for c in children if lower in c.search_blob().lower()]

    def _children(self) -> list[_Node]:
        return self._filter(self._current().children)

    def _selected(self) -> _Node | None:
        children = self._children()
        if not children:
            return None
        self.state.cursor = max(0, min(self.state.cursor, len(children) - 1))
        return children[self.state.cursor]

    def _header(self) -> list[tuple[str, str]]:
        return [("class:header", f"  {self.title}  ")]

    def _breadcrumb(self) -> list[tuple[str, str]]:
        trail = " > ".join(n.label for n in self.state.path)
        return [("", f"Path: {trail}")]

    def _list_fragments(self) -> list[tuple[str, str]]:
        fragments: list[tuple[str, str]] = []
        for i, node in enumerate(self._children()):
            style = "class:row.selected" if i == self.state.cursor else ""
            marker = "▸" if i == self.state.cursor else " "
            fragments.append((style, f" {marker} {node.label}\n"))
        return fragments

    def _preview_panel(self, node: _Node | None) -> Panel | None:
        if node is None:
            return None

        plugin = node if node.kind == "item" else None
        intensity = node if node.kind == "variant" else None

        if node.kind == "variant" and len(self.state.path) >= 2:
            plugin = self.state.path[-1]
        elif node.children and node.kind != "root":
            plugin = node

        text = Text()
        text.append("Item\n", style="bold")
        text.append(f"  {plugin.label if plugin else '-'}\n")
        desc = plugin.description if plugin and plugin.description else "-"
        tags = ", ".join(plugin.tags) if plugin and plugin.tags else "-"
        text.append(f"  tags: {tags}\n")
        text.append(f"  desc: {desc}\n\n")

        text.append("Variant\n", style="bold")
        text.append(f"  {intensity.label if intensity else '-'}\n")
        idesc = intensity.description if intensity and intensity.description else "-"
        text.append(f"  desc: {idesc}\n\n")

        hint = "Confirm: press Enter to select"
        if node.children:
            hint = "Next: press Enter to pick variant"
        text.append(hint, style="italic")

        return Panel(text, title="Preview", border_style="cyan", padding=(1, 2))

    def _preview_ansi(self) -> ANSI:
        node = self._selected()
        if node is None:
            return ANSI("")
        with self.rich.capture() as cap:
            panel = self._preview_panel(node)
            if panel:
                self.rich.print(panel)
        return ANSI(cap.get())

    def _on_query_changed(self) -> None:
        self.state.query = self.search.text
        self.state.cursor = 0
        self.app.invalidate()

    def _bindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("down")
        def _(event: Any) -> None:
            self.state.cursor += 1
            event.app.invalidate()

        @kb.add("up")
        def _(event: Any) -> None:
            self.state.cursor -= 1
            event.app.invalidate()

        @kb.add("enter")
        def _(event: Any) -> None:
            node = self._selected()
            if node is None:
                return
            if node.children:
                self.state.path.append(node)
                self.state.cursor = 0
                self.search.text = ""
                return
            event.app.exit(result=node)

        @kb.add("left")
        @kb.add("backspace")
        def _(event: Any) -> None:
            if len(self.state.path) > 1:
                self.state.path.pop()
                self.state.cursor = 0
                self.search.text = ""
                event.app.invalidate()

        @kb.add("escape")
        def _(event: Any) -> None:
            event.app.exit(result=None)

        return kb

    def run(self) -> _Node | None:
        return self.app.run()


class _TwoLevelMultiPicker:
    """Two-level picker that allows selecting one variant per item in a single pass."""

    def __init__(self, root: _Node, *, title: str, query_hint: str = "") -> None:
        self.state = _PickerState(path=[root], cursor=0, query=query_hint)
        self.selected: dict[str, _Node] = {}
        self.title = title
        self.rich = Console(force_terminal=True, color_system="truecolor")

        self.search = TextArea(height=1, prompt="Search: ", multiline=False)
        if query_hint:
            self.search.text = query_hint

        self.list_control = FormattedTextControl(self._list_fragments, focusable=True)
        self.preview_control = FormattedTextControl(self._preview_ansi)
        self.kb = self._bindings()

        root_container = HSplit(
            [
                Window(height=1, content=FormattedTextControl(self._header)),
                Window(height=1, content=FormattedTextControl(self._breadcrumb)),
                self.search,
                Window(height=1, char="-", style="class:separator"),
                VSplit(
                    [
                        Window(self.list_control, width=Dimension(weight=1)),
                        Window(width=1, char="|", style="class:separator"),
                        Window(self.preview_control, width=Dimension(weight=1)),
                    ],
                    padding=1,
                ),
            ]
        )

        self.app = Application(
            layout=Layout(root_container, focused_element=self.search),
            key_bindings=self.kb,
            style=Style.from_dict(
                {
                    "header": "bold",
                    "row.selected": "reverse",
                    "checked": "bold",
                    "separator": "fg:#0000aa",
                    "search": "bg:#eeeeee fg:#000000",
                }
            ),
            full_screen=True,
        )

        self.search.buffer.on_text_changed += lambda _: self._on_query_changed()

    def _header(self) -> list[tuple[str, str]]:
        hint = "Space=toggle (defaults to medium), Right=drill, Enter=save, Ctrl+S=save, Esc=cancel"
        return [("class:header", f"  {self.title}  ({hint})  ")]

    def _breadcrumb(self) -> list[tuple[str, str]]:
        trail = " > ".join(n.label for n in self.state.path)
        return [("", f"Path: {trail}")]

    def _current(self) -> _Node:
        return self.state.path[-1]

    def _filter(self, children: list[_Node]) -> list[_Node]:
        query = self.state.query.strip()
        if not query:
            return children
        if _HAS_RAPIDFUZZ:
            matches = process.extract(
                query,
                [(c.search_blob(), c) for c in children],
                scorer=fuzz.WRatio,
            )
            return [m[0][1] for m in matches]
        lower = query.lower()
        return [c for c in children if lower in c.search_blob().lower()]

    def _children(self) -> list[_Node]:
        return self._filter(self._current().children)

    def _selected_node(self) -> _Node | None:
        children = self._children()
        if not children:
            return None
        self.state.cursor = max(0, min(self.state.cursor, len(children) - 1))
        return children[self.state.cursor]

    def _is_checked(self, node: _Node) -> bool:
        if node.kind == "variant":
            return self.selected.get(node.parent_id or "") is node
        if node.kind == "item" and node.children:
            return self.selected.get(node.id) is not None
        if node.kind == "item" and not node.children:
            return node.id in self.selected
        return False

    def _list_fragments(self) -> list[tuple[str, str]]:
        fragments: list[tuple[str, str]] = []
        for i, node in enumerate(self._children()):
            selected = i == self.state.cursor
            checked = self._is_checked(node)
            style = "class:row.selected" if selected else ""
            if checked and not selected:
                style = "class:checked"
            marker = "▸" if selected else " "
            checkbox = "[x]" if checked else "[ ]"
            fragments.append((style, f" {marker} {checkbox} {node.label}\n"))
        return fragments

    def _preview_panel(self, node: _Node | None) -> Panel | None:
        if node is None:
            return None

        plugin = node if node.kind == "item" else None
        intensity = node if node.kind == "variant" else None
        if node.kind == "variant" and len(self.state.path) >= 2:
            plugin = self.state.path[-1]

        text = Text()
        text.append("Item\n", style="bold")
        text.append(f"  {plugin.label if plugin else '-'}\n")
        desc = plugin.description if plugin and plugin.description else "-"
        tags = ", ".join(plugin.tags) if plugin and plugin.tags else "-"
        text.append(f"  tags: {tags}\n")
        text.append(f"  desc: {desc}\n\n")

        text.append("Variant\n", style="bold")
        text.append(f"  {intensity.label if intensity else '-'}\n")
        idesc = intensity.description if intensity and intensity.description else "-"
        text.append(f"  desc: {idesc}\n\n")

        text.append("Right to drill variants, space to toggle (default medium), Enter to submit", style="italic")

        return Panel(text, title="Preview", border_style="cyan", padding=(1, 2))

    def _preview_ansi(self) -> ANSI:
        node = self._selected_node()
        if node is None:
            return ANSI("")
        with self.rich.capture() as cap:
            panel = self._preview_panel(node)
            if panel:
                self.rich.print(panel)
        return ANSI(cap.get())

    def _toggle_selection(self, node: _Node | None) -> None:
        if node is None:
            return
        # Leaf with variants uses parent_id mapping; leaf without children uses its own id.
        if node.kind == "variant":
            parent_id = node.parent_id or ""
            current = self.selected.get(parent_id)
            if current is node:
                del self.selected[parent_id]
            else:
                self.selected[parent_id] = node
        elif node.children:
            if node.id in self.selected:
                del self.selected[node.id]
            else:
                # Default to "medium" variant if present, else first child.
                default_child = None
                for child in node.children:
                    tail = child.id.split(":", 1)[-1].lower()
                    if child.label.lower() == "medium" or tail == "medium":
                        default_child = child
                        break
                if default_child is None and node.children:
                    default_child = node.children[0]
                if default_child is not None:
                    self.selected[node.id] = default_child
        elif not node.children:
            if node.id in self.selected:
                del self.selected[node.id]
            else:
                self.selected[node.id] = node
        self.app.invalidate()

    def _on_query_changed(self) -> None:
        self.state.query = self.search.text
        self.state.cursor = 0
        self.app.invalidate()

    def _exit(self, result: Any) -> None:
        try:
            self.app.exit(result=result)
        except Exception as exc:  # pragma: no cover - defensive
            if "Return value already set" not in str(exc):
                raise

    def _bindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("down")
        def _(event: Any) -> None:
            self.state.cursor += 1
            event.app.invalidate()

        @kb.add("up")
        def _(event: Any) -> None:
            self.state.cursor -= 1
            event.app.invalidate()

        @kb.add("enter")
        def _(event: Any) -> None:
            node = self._selected_node()
            if node is None:
                return
            # Enter confirms current selection set; drill uses Right key
            self._exit(self._build_result())

        @kb.add("space")
        def _(event: Any) -> None:
            self._toggle_selection(self._selected_node())

        @kb.add("right")
        def _(event: Any) -> None:
            node = self._selected_node()
            if node and node.children:
                self.state.path.append(node)
                self.state.cursor = 0
                self.search.text = ""

        @kb.add("left")
        @kb.add("backspace")
        def _(event: Any) -> None:
            if len(self.state.path) > 1:
                self.state.path.pop()
                self.state.cursor = 0
                self.search.text = ""
                event.app.invalidate()

        @kb.add("c-s")
        @kb.add("c-j")
        def _(event: Any) -> None:
            self._exit(self._build_result())

        @kb.add("escape")
        def _(event: Any) -> None:
            event.app.exit(result=None)

        return kb

    def _build_result(self) -> list[PickItem]:
        # Preserve insertion order of selections.
        return [node.payload for node in self.selected.values() if node.payload is not None]

    def run(self) -> list[PickItem] | None:
        return self.app.run()


def _clone_variant(parent_id: str, variant: PickItem) -> PickItem:
    """Clone a variant item with a parent-qualified id for round-tripping."""
    qualified_id = variant.id if ":" in variant.id else f"{parent_id}:{variant.id}"
    return PickItem(
        id=qualified_id,
        title=variant.title,
        tags=variant.tags,
        description=variant.description,
        search_blob=variant.search_blob or variant.title,
        preview=variant.preview,
        payload=variant.payload,
        variants=variant.variants,
    )


def _build_tree(items: Sequence[PickItem]) -> _Node:
    root = _Node(id="root", label="Items", kind="root")
    root.children = []
    for item in items:
        node = _Node(
            id=item.id,
            label=item.title,
            kind="item",
            tags=item.tags,
            description=item.description or "",
            payload=item,
        )
        if item.variants:
            node.children = [
                _Node(
                    id=_clone_variant(item.id, variant).id,
                    label=variant.title,
                    kind="variant",
                    tags=variant.tags,
                    description=variant.description or "",
                    payload=_clone_variant(item.id, variant),
                    parent_id=item.id,
                )
                for variant in item.variants
            ]
        root.children.append(node)
    return root


class _PickerApp:
    def __init__(self, items: Sequence[PickItem], title: str, multi_select: bool = False):
        self.items: list[PickItem] = list(items)
        self._item_index_by_objid: dict[int, int] = {
            id(item): idx for idx, item in enumerate(self.items)
        }

        self.title = title
        self.multi_select = multi_select

        self.selections: dict[int, int | None] = {}
        self.show_variants = False
        self.variant_index = 0

        self._panel = FlatPickerPanel(self.items, row_renderer=self._render_row)
        self.search = self._panel.search
        self.list_control = self._panel.list_control
        self.preview_control = self._panel.preview_control

        self.variants_control = FormattedTextControl(self._render_variants, focusable=True)

        self.kb = self._keybindings()

        def get_right_pane() -> AnyContainer:
            if self.show_variants:
                return Window(self.variants_control)
            return Window(self.preview_control)

        # Inner content layout
        inner_layout = HSplit(
            [
                self.search,
                Window(height=1, char="-", style="class:separator"),
                VSplit(
                    [
                        Window(self.list_control, width=Dimension(weight=1)),
                        Window(width=1, char="|", style="class:separator"),
                        DynamicContainer(get_right_pane),
                    ],
                    padding=1,
                ),
            ]
        )
        
        root_container = Frame(inner_layout, title=title)

        self.app: Application = Application(
            layout=Layout(root_container, focused_element=self.search),
            key_bindings=self.kb,
            style=Style.from_dict({
                "selected": "bg:#0000aa fg:white bold",
                "checked": "fg:#00ff00 bold",
                "separator": "fg:#0000aa",
                "frame.border": "fg:#0000aa",
                "frame.label": "fg:#0000aa bold",
                "search": "bg:#eeeeee fg:#000000",
                "variant-selected": "bg:#005500 fg:white bold",
            }),
            full_screen=True,
        )

        self.search.buffer.on_text_changed += lambda _: self._apply_filter()

    def _exit(self, app: Application, result: Any) -> None:
        """Exit the prompt safely, ignoring duplicate-exit errors."""
        try:
            app.exit(result=result)
        except Exception as exc:  # pragma: no cover - defensive
            if "Return value already set" in str(exc):
                return
            raise

    def _apply_filter(self) -> None:
        self._panel.apply_filter(reset_index=True)
        if hasattr(self, "app"):
            self.app.invalidate()

    @property
    def filtered(self) -> list[PickItem]:
        return self._panel.filtered

    @property
    def index(self) -> int:
        return self._panel.selected_index

    @index.setter
    def index(self, value: int) -> None:
        self._panel.selected_index = value

    def _render_row(self, item: PickItem, is_selected: bool) -> tuple[str, str]:
        original_idx = self._item_index_by_objid.get(id(item), -1)

        prefix = "[ ]" if self.multi_select else "   "
        suffix = ""
        checked = original_idx in self.selections
        if checked:
            prefix = "[x]"
            var_idx = self.selections.get(original_idx)
            if item.variants and var_idx is not None:
                try:
                    v_title = item.variants[var_idx].title
                except IndexError:
                    v_title = ""
                if v_title:
                    suffix = f" [{v_title}]"

        style = ""
        if is_selected:
            style = "class:selected"
        elif checked:
            style = "class:checked"

        return style, f" {prefix} {item.title}{suffix}"

    def _render_variants(self) -> list[tuple[str, str]]:
        if not self.filtered:
            return []
        item = self.filtered[self.index]
        if not item.variants:
            return [("", "No options available")]

        frags: list[tuple[str, str]] = []
        frags.append(("class:title", f"Select Option for {item.title}:\n\n"))
        for i, var in enumerate(item.variants):
            style = ""
            if i == self.variant_index:
                style = "class:variant-selected"
            frags.append((style, f" > {var.title}\n"))
        return frags

    def _keybindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("down")
        def _(e: Any) -> None:
            if self.show_variants:
                self._move_variant(1)
            else:
                self._move(1)

        @kb.add("up")
        def _(e: Any) -> None:
            if self.show_variants:
                self._move_variant(-1)
            else:
                self._move(-1)

        @kb.add("enter")
        def _(e: Any) -> None:
            if not self.filtered:
                return

            if self.show_variants:
                self._confirm_variant()
                return

            current_item = self.filtered[self.index]

            if self.multi_select:
                self._exit(e.app, self._build_multi_result())
                return

            if current_item.variants:
                self._open_variants()
            else:
                self._exit(e.app, current_item)

        @kb.add("right")
        def _(e: Any) -> None:
            if not self.show_variants and self.filtered:
                current_item = self.filtered[self.index]
                if current_item.variants:
                    self._open_variants()

        @kb.add("left")
        def _(e: Any) -> None:
            if self.show_variants:
                self.show_variants = False
                self.app.layout.focus(self.search) 
                self.app.invalidate()

        @kb.add("escape")
        def _(e: Any) -> None:
            if self.show_variants:
                self.show_variants = False
                self.app.layout.focus(self.search)
                self.app.invalidate()
            else:
                self._exit(e.app, None)

        @kb.add("space")
        def _(e: Any) -> None:
            if not self.show_variants and self.multi_select and self.filtered:
                current_item = self.filtered[self.index]
                self._toggle_selection(current_item, default_variant=0 if current_item.variants else None)

        @kb.add("c-r")
        def _(e: Any) -> None:
            if self.show_variants:
                self.show_variants = False
                self.app.layout.focus(self.search)
            self._panel.reset_filter()
            self.app.invalidate()

        @kb.add("c-c")
        def _(e: Any) -> None:
            e.app.exit(result=None)

        return kb

    def _open_variants(self) -> None:
        self.show_variants = True
        self.variant_index = 0
        self.app.layout.focus(self.variants_control)
        self.app.invalidate()

    def _move(self, delta: int) -> None:
        self._panel.move(delta)
        self.app.invalidate()

    def _move_variant(self, delta: int) -> None:
        current_item = self.filtered[self.index]
        if not current_item.variants:
            return
        self.variant_index = max(0, min(self.variant_index + delta, len(current_item.variants) - 1))
        self.app.invalidate()

    def _toggle_selection(self, item: PickItem, default_variant: int | None = None) -> None:
        try:
            idx = self.items.index(item)
            if idx in self.selections:
                del self.selections[idx]
            else:
                self.selections[idx] = default_variant
        except ValueError:
            pass
        self.app.invalidate()

    def _confirm_variant(self) -> None:
        current_item = self.filtered[self.index]
        try:
            idx = self.items.index(current_item)
        except ValueError:
            return

        self.selections[idx] = self.variant_index
        self.show_variants = False
        self.app.layout.focus(self.search)

        if not self.multi_select:
            self._exit(self.app, self._build_result(idx))
        else:
            self.app.invalidate()

    def _build_result(self, idx: int) -> PickItem:
        parent = self.items[idx]
        var_idx = self.selections.get(idx)
        if var_idx is not None and parent.variants:
            try:
                return parent.variants[var_idx]
            except IndexError:
                pass
        return parent

    def _build_multi_result(self) -> list[PickItem]:
        final_list = []
        for idx in sorted(self.selections.keys()):
            final_list.append(self._build_result(idx))
        return final_list

    def run(self) -> Any:
        return self.app.run()


class PowerPicker(Picker):
    def pick_one(
        self,
        items: Sequence[PickItem],
        *,
        title: str,
        query_hint: str = ""
    ) -> PickItem | None:
        if not items:
            return None
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            return None
        has_variants = any(item.variants for item in items)
        if has_variants:
            tree = _build_tree(items)
            picker = _TwoLevelPicker(tree, title=title, query_hint=query_hint)
            selected = picker.run()
            return selected.payload if selected else None

        app = _PickerApp(items, title, multi_select=False)
        if query_hint:
            app.search.text = query_hint
        return app.run()

    def pick_many(
        self,
        items: Sequence[PickItem],
        *,
        title: str,
        query_hint: str = ""
    ) -> list[PickItem]:
        if not items:
            return []
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            return []
        has_variants = any(item.variants for item in items)
        if has_variants:
            tree = _build_tree(items)
            picker = _TwoLevelMultiPicker(tree, title=title, query_hint=query_hint)
            result = picker.run()
            return result if result is not None else []
        app = _PickerApp(items, title, multi_select=True)
        if query_hint:
            app.search.text = query_hint
        result = app.run()
        return result if result is not None else []
