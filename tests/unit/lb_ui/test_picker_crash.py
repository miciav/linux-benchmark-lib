from dataclasses import dataclass
from typing import Any

import pytest

from lb_ui.api import PickItem
from lb_ui.tui.system.components import flat_picker_panel as panel_module
from lb_ui.tui.system.components.flat_picker_panel import FlatPickerPanel

pytestmark = pytest.mark.unit_ui


@dataclass
class UnhashablePayload:
    data: dict[str, Any]

    def __hash__(self):
        raise TypeError("unhashable type: 'UnhashablePayload'")


def test_picker_filter_with_unhashable_payload():
    """
    Verify that the picker filtering does not crash when items contain unhashable
    payloads. This reproduces the 'Exception unhashable type: WorkloadConfig'
    error found with rapidfuzz.
    """
    # Create items with unhashable payload
    items = [
        PickItem(id="1", title="Item One", payload=UnhashablePayload({"a": 1})),
        PickItem(id="2", title="Item Two", payload=UnhashablePayload({"b": 2})),
    ]

    panel = FlatPickerPanel(
        items, row_renderer=lambda item, is_selected: ("", item.title)
    )
    panel.search.text = "One"

    # Manually trigger the filter logic (normally triggered by callback).
    try:
        panel.apply_filter(reset_index=True)
    except TypeError as e:
        pytest.fail(f"Picker crashed on filtering unhashable payload: {e}")
    except Exception as e:
        pytest.fail(f"Picker crashed with unexpected error: {e}")

    # Verify filtering worked
    assert len(panel.filtered) == 1
    assert panel.filtered[0].title == "Item One"


def test_flat_picker_filter_uses_string_choices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    items = [
        PickItem(id="one", title="Alpha"),
        PickItem(id="two", title="Beta"),
    ]
    panel = FlatPickerPanel(
        items, row_renderer=lambda item, is_selected: ("", item.title)
    )
    panel.search.text = "alp"

    def fake_extract(query, choices, scorer=None, **kwargs):
        assert all(isinstance(choice, str) for choice in choices)
        assert choices[0].startswith("Alpha")
        assert choices[1].startswith("Beta")
        return [(choices[0], 100, 0)]

    class DummyProcess:
        @staticmethod
        def extract(query, choices, scorer=None, **kwargs):
            return fake_extract(query, choices, scorer=scorer, **kwargs)

    monkeypatch.setattr(panel_module, "has_fuzzy_search", lambda: True)
    monkeypatch.setattr(
        panel_module,
        "fuzzy_matcher",
        lambda: (DummyProcess, object()),
    )

    panel.apply_filter(reset_index=True)
    assert [item.title for item in panel.filtered] == ["Alpha"]
