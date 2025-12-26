import pytest

from lb_ui.tui.system.components import picker as picker_module
from lb_ui.tui.system.models import PickItem

pytestmark = pytest.mark.unit_ui


def test_picker_app_seeds_selected_items() -> None:
    items = [
        PickItem(id="a", title="A", selected=True),
        PickItem(id="b", title="B"),
        PickItem(id="c", title="C", selected=True),
    ]

    app = picker_module._PickerApp(items, title="Test", multi_select=True)

    assert set(app.selections.keys()) == {0, 2}
    assert app.selections[0] is None
    assert app.selections[2] is None


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

    tree = picker_module._build_tree(items)
    picker = picker_module._TwoLevelMultiPicker(tree, title="Test")

    assert "stress_ng" in picker.selected
    assert picker.selected["stress_ng"].label == "high"
    assert "fio" not in picker.selected


def test_two_level_picker_defaults_to_medium_variant() -> None:
    variants = [
        PickItem(id="low", title="low"),
        PickItem(id="medium", title="medium"),
        PickItem(id="high", title="high"),
    ]
    items = [
        PickItem(id="stress_ng", title="stress_ng", variants=variants, selected=True),
    ]

    tree = picker_module._build_tree(items)
    picker = picker_module._TwoLevelMultiPicker(tree, title="Test")

    assert picker.selected["stress_ng"].label == "medium"


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

    tree = picker_module._build_tree(items)
    picker = picker_module._TwoLevelMultiPicker(tree, title="Test")

    assert picker.selected == {}
