import pytest
from dataclasses import dataclass
from typing import Any
from lb_ui.api import _PickerApp
from lb_ui.api import PickItem
from lb_ui.tui.system.components import picker as picker_module

pytestmark = pytest.mark.unit_ui

@dataclass
class UnhashablePayload:
    data: dict[str, Any]
    
    def __hash__(self):
        raise TypeError("unhashable type: 'UnhashablePayload'")

def test_picker_filter_with_unhashable_payload():
    """
    Verify that the picker filtering does not crash when items contain unhashable payloads.
    This reproduces the 'Exception unhashable type: WorkloadConfig' error found with rapidfuzz.
    """
    # Create items with unhashable payload
    items = [
        PickItem(id="1", title="Item One", payload=UnhashablePayload({"a": 1})),
        PickItem(id="2", title="Item Two", payload=UnhashablePayload({"b": 2})),
    ]
    
    app = _PickerApp(items, title="Test Picker")
    
    # Simulate typing in search box to trigger filtering
    app.search.text = "One"
    
    # Manually trigger the filter logic (normally triggered by callback)
    try:
        app._apply_filter()
    except TypeError as e:
        pytest.fail(f"Picker crashed on filtering unhashable payload: {e}")
    except Exception as e:
        pytest.fail(f"Picker crashed with unexpected error: {e}")

    # Verify filtering worked
    assert len(app.filtered) == 1
    assert app.filtered[0].title == "Item One"


def test_two_level_picker_filter_uses_string_choices(monkeypatch: pytest.MonkeyPatch) -> None:
    root = picker_module._Node(id="root", label="Root", kind="root")
    child_one = picker_module._Node(id="one", label="Alpha", kind="item")
    child_two = picker_module._Node(id="two", label="Beta", kind="item")
    root.children = [child_one, child_two]

    picker = picker_module._TwoLevelMultiPicker(root, title="Test")
    picker.state.query = "alp"

    def fake_extract(query, choices, scorer=None):
        assert all(isinstance(choice, str) for choice in choices)
        assert choices[0].startswith("Alpha")
        assert choices[1].startswith("Beta")
        return [(choices[0], 100, 0)]

    class DummyFuzz:
        WRatio = object()

    monkeypatch.setattr(picker_module, "_HAS_RAPIDFUZZ", True)
    monkeypatch.setattr(picker_module, "process", type("Proc", (), {"extract": fake_extract}), raising=False)
    monkeypatch.setattr(picker_module, "fuzz", DummyFuzz(), raising=False)

    results = picker._filter(root.children)
    assert results == [child_one]
