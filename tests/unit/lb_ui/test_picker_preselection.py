import pytest

from lb_ui.tui.system.models import PickItem
from lb_ui.tui.screens.picker_screen import PickerSelectionState

pytestmark = pytest.mark.unit_ui


def test_picker_app_seeds_selected_items() -> None:
    items = [
        PickItem(id="a", title="A", selected=True),
        PickItem(id="b", title="B"),
        PickItem(id="c", title="C", selected=True),
    ]

    state = PickerSelectionState(items)
    state.seed_from_items()

    assert set(state.selections.keys()) == {0, 2}
    assert state.selections[0] is None
    assert state.selections[2] is None


def test_two_level_picker_seeds_variant_selection() -> None:
    variants = [
        PickItem(id="low", title="low"),
        PickItem(id="medium", title="medium"),
        PickItem(id="high", title="high", selected=True),
    ]
    items = [
        PickItem(id="stress_ng", title="stress_ng", variants=variants, selected=True),
        PickItem(id="fio", title="fio"),
    ]

    state = PickerSelectionState(items)
    state.seed_from_items()

    selected_idx = state.selections.get(0)
    assert selected_idx is not None
    assert items[0].variants[selected_idx].title == "high"
    assert 1 not in state.selections


def test_two_level_picker_defaults_to_medium_variant() -> None:
    variants = [
        PickItem(id="low", title="low"),
        PickItem(id="medium", title="medium"),
        PickItem(id="high", title="high"),
    ]
    items = [
        PickItem(id="stress_ng", title="stress_ng", variants=variants, selected=True),
    ]

    state = PickerSelectionState(items)
    state.seed_from_items()

    selected_idx = state.selections.get(0)
    assert selected_idx is not None
    assert items[0].variants[selected_idx].title == "medium"


def test_two_level_picker_ignores_disabled_items() -> None:
    variants = [
        PickItem(id="low", title="low"),
        PickItem(id="high", title="high", selected=True),
    ]
    items = [
        PickItem(
            id="stress_ng",
            title="stress_ng",
            variants=variants,
            selected=True,
            disabled=True,
        ),
    ]

    state = PickerSelectionState(items)
    state.seed_from_items()

    assert state.selections == {}
