"""Reusable flat picker panel (search + list + preview) for prompt_toolkit UIs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, TypeAlias, Sequence

from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import TextArea
from rapidfuzz import fuzz, process
from rich.console import Console
from rich.text import Text

from lb_ui.tui.system.models import PickItem

RowFragment: TypeAlias = tuple[str, str]
RowRenderer: TypeAlias = Callable[[PickItem, bool], RowFragment]
PreviewRenderer: TypeAlias = Callable[[PickItem], object | None]


@dataclass(frozen=True)
class FlatPickerPanelConfig:
    """Configuration for FlatPickerPanel behavior."""

    enable_fuzzy: bool = True
    fuzzy_limit: int = 200
    fuzzy_score_cutoff: int = 50
    wrap_navigation: bool = False


class FlatPickerPanel:
    """A reusable search + list + preview component.

    This panel owns the list filtering + selection index state, but does not own an
    Application; callers wire keybindings and invalidation as needed.
    """

    def __init__(
        self,
        items: Sequence[PickItem],
        *,
        row_renderer: RowRenderer,
        preview_renderer: PreviewRenderer | None = None,
        fallback_preview_renderer: PreviewRenderer | None = None,
        search_prompt: str = "Search: ",
        search_style: str = "class:search",
        config: FlatPickerPanelConfig | None = None,
    ) -> None:
        self._config = config or FlatPickerPanelConfig()
        self._console = Console(force_terminal=True)

        self._row_renderer = row_renderer
        self._preview_renderer = preview_renderer or (lambda item: item.preview)
        self._fallback_preview_renderer = fallback_preview_renderer or (
            lambda item: Text(item.description) if item.description else None
        )

        self.search = TextArea(height=1, prompt=search_prompt, style=search_style)

        self._items: list[PickItem] = list(items)
        self._filtered: list[PickItem] = []
        self._selected_index = 0
        self._filter_text = ""

        self.list_control = FormattedTextControl(self._render_list, focusable=True)
        self.preview_control = FormattedTextControl(self._render_preview)

        self.apply_filter(reset_index=True)

    @property
    def items(self) -> list[PickItem]:
        """Return the full (unfiltered) items list."""

        return self._items

    @property
    def filtered(self) -> list[PickItem]:
        """Return the filtered items list."""

        return self._filtered

    @property
    def filter_text(self) -> str:
        """Return the current filter text."""

        return self._filter_text

    @property
    def selected_index(self) -> int:
        """Return the selected index in the filtered list."""

        return self._selected_index

    @selected_index.setter
    def selected_index(self, value: int) -> None:
        self._selected_index = self._clamp_index(value)

    @property
    def selected_item(self) -> PickItem | None:
        """Return the currently selected item, if any."""

        if not self._filtered:
            return None
        idx = self._clamp_index(self._selected_index)
        if idx < 0 or idx >= len(self._filtered):
            return None
        return self._filtered[idx]

    def set_items(self, items: Sequence[PickItem], *, keep_filter: bool = False) -> None:
        """Replace items and re-apply filtering."""

        self._items = list(items)
        if not keep_filter:
            self.search.text = ""
            self._filter_text = ""
        self.apply_filter(reset_index=True)

    def apply_filter(self, *, reset_index: bool = True) -> None:
        """Apply search filter to items."""

        query = self.search.text.strip()
        self._filter_text = query
        self._filtered = self._filter_items(self._items, query)
        if reset_index:
            self._selected_index = 0
        else:
            self._selected_index = self._clamp_index(self._selected_index)

    def reset_filter(self) -> None:
        """Clear filter text and re-apply."""

        self.search.text = ""
        self.apply_filter(reset_index=True)

    def move(self, delta: int) -> None:
        """Move selection up/down."""

        if not self._filtered:
            return
        if self._config.wrap_navigation:
            self._selected_index = (self._selected_index + delta) % len(self._filtered)
            return
        self._selected_index = self._clamp_index(self._selected_index + delta)

    def _clamp_index(self, value: int) -> int:
        if not self._filtered:
            return 0
        return max(0, min(value, len(self._filtered) - 1))

    def _filter_items(self, items: list[PickItem], query: str) -> list[PickItem]:
        if not query:
            return list(items)

        if not self._config.enable_fuzzy:
            q = query.lower()
            return [
                it
                for it in items
                if q in (it.search_blob or it.title).lower()
                or q in (it.description or "").lower()
            ]

        choices = [it.search_blob or it.title for it in items]
        matches = process.extract(
            query,
            choices,
            scorer=fuzz.WRatio,
            limit=self._config.fuzzy_limit,
            score_cutoff=self._config.fuzzy_score_cutoff,
        )
        # matches is list of (match_string, score, index)
        return [items[m[2]] for m in matches]

    def _render_list(self) -> list[RowFragment]:
        frags: list[RowFragment] = []
        for i, item in enumerate(self._filtered):
            style, text = self._row_renderer(item, i == self._selected_index)
            if not text.endswith("\n"):
                text = f"{text}\n"
            frags.append((style, text))
        return frags

    def _render_preview(self) -> ANSI:
        item = self.selected_item
        if item is None:
            return ANSI("")

        renderable = self._preview_renderer(item)
        if renderable is None:
            renderable = self._fallback_preview_renderer(item)
        if renderable is None:
            return ANSI("")

        with self._console.capture() as cap:
            self._console.print(renderable)
        return ANSI(cap.get())

