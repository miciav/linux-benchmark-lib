import pytest
from dataclasses import dataclass
from typing import Any
from lb_ui.ui.system.components.picker import _PickerApp
from lb_ui.ui.system.models import PickItem

pytestmark = pytest.mark.ui

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
