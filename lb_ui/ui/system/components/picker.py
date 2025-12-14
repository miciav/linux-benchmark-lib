from __future__ import annotations

import sys
from typing import Any, Sequence

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout, HSplit, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import Frame
from prompt_toolkit.styles import Style
from prompt_toolkit.layout.containers import DynamicContainer, AnyContainer
from prompt_toolkit.layout.dimension import Dimension

from lb_ui.ui.system.components.flat_picker_panel import FlatPickerPanel
from lb_ui.ui.system.models import PickItem
from lb_ui.ui.system.protocols import Picker


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
                e.app.exit(result=self._build_multi_result())
                return

            if current_item.variants:
                self._open_variants()
            else:
                e.app.exit(result=current_item)

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
                e.app.exit(result=None)

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
            self.app.exit(result=self._build_result(idx))
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
        app = _PickerApp(items, title, multi_select=True)
        if query_hint:
            app.search.text = query_hint
        result = app.run()
        return result if result is not None else []
