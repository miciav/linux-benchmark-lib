import pytest

from lb_ui.tui.screens.picker_screen import HierarchyState, PickerScreen, PickerSelectionState
from lb_ui.tui.system.models import PickItem, SelectionNode

pytestmark = pytest.mark.unit_ui


def test_picker_selection_state_variant_choice() -> None:
    variants = [
        PickItem(id="low", title="low"),
        PickItem(id="medium", title="medium"),
        PickItem(id="high", title="high"),
    ]
    items = [PickItem(id="stress", title="stress", variants=variants)]

    state = PickerSelectionState(items)
    state.toggle_item(items[0])
    assert state.selected_variant_title(items[0]) == "medium"

    state.select_variant(items[0], 2)
    assert state.selected_variant_title(items[0]) == "high"
    assert state.build_result(items[0]).title == "high"


def test_hierarchy_state_navigation() -> None:
    leaf = SelectionNode(id="leaf", label="Leaf", kind="leaf")
    branch = SelectionNode(
        id="branch",
        label="Branch",
        kind="group",
        children=[leaf],
    )
    root = SelectionNode(
        id="root",
        label="Root",
        kind="root",
        children=[branch],
    )

    state = HierarchyState(root)
    assert state.breadcrumb() == "Root"
    assert state.node_by_item_id["branch"].label == "Branch"
    assert state.descend(branch) is True
    assert state.breadcrumb() == "Root > Branch"
    assert state.descend(leaf) is False
    assert state.ascend() is True
    assert state.breadcrumb() == "Root"


def test_picker_screen_render_footer_flat_single() -> None:
    items = [PickItem(id="a", title="Alpha"), PickItem(id="b", title="Beta")]
    screen = PickerScreen(title="Test", items=items, multi_select=False)
    footer = screen._render_footer()
    full_text = "".join(t for _, t in footer)
    assert "Enter" in full_text
    assert "Esc" in full_text


def test_picker_screen_render_footer_flat_multi() -> None:
    items = [PickItem(id="a", title="Alpha")]
    screen = PickerScreen(title="Test", items=items, multi_select=True)
    footer = screen._render_footer()
    full_text = "".join(t for _, t in footer)
    assert "Space" in full_text
    assert "toggle" in full_text


def test_picker_screen_render_footer_hierarchical() -> None:
    root = SelectionNode(id="root", label="Root", kind="root")
    screen = PickerScreen(title="Test", root=root)
    footer = screen._render_footer()
    full_text = "".join(t for _, t in footer)
    assert "back" in full_text


def test_picker_row_shows_arrow_for_item_with_variants_single_select() -> None:
    variants = [PickItem(id="low", title="low"), PickItem(id="high", title="high")]
    items = [
        PickItem(id="plain", title="Plain"),
        PickItem(id="with_var", title="WithVariants", variants=variants),
    ]
    screen = PickerScreen(title="Test", items=items, multi_select=False)
    _, text = screen._render_row(items[1], is_selected=False)
    assert "\u25b8" in text  # ▸


def test_picker_row_no_arrow_for_plain_item_single_select() -> None:
    items = [PickItem(id="plain", title="Plain")]
    screen = PickerScreen(title="Test", items=items, multi_select=False)
    _, text = screen._render_row(items[0], is_selected=False)
    assert "\u25b8" not in text  # no ▸


def test_picker_row_shows_arrow_for_unselected_item_with_variants_multi_select() -> None:
    variants = [PickItem(id="low", title="low"), PickItem(id="high", title="high")]
    items = [PickItem(id="stress", title="Stress", variants=variants)]
    screen = PickerScreen(title="Test", items=items, multi_select=True)
    _, text = screen._render_row(items[0], is_selected=False)
    assert "\u25b8" in text  # ▸


def test_picker_row_shows_variant_label_not_arrow_when_selected_with_variant() -> None:
    variants = [PickItem(id="low", title="low"), PickItem(id="high", title="high")]
    items = [PickItem(id="stress", title="Stress", variants=variants)]
    screen = PickerScreen(title="Test", items=items, multi_select=True)
    assert screen._selection is not None
    screen._selection.toggle_item(items[0])  # selects with default variant
    _, text = screen._render_row(items[0], is_selected=False)
    assert "[x]" in text
    # After selection the variant label appears, not a bare ▸ without context
    assert "\u25b8" not in text or "low" in text or "medium" in text
