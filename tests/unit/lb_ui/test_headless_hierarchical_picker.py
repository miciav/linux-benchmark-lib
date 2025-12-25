"""Tests for the headless hierarchical picker behavior."""

import pytest

from lb_ui.tui.system.headless import HeadlessUI
from lb_ui.tui.system.models import SelectionNode


pytestmark = pytest.mark.unit_ui


def _sample_tree() -> SelectionNode:
    return SelectionNode(
        id="root",
        label="Root",
        kind="root",
        children=[
            SelectionNode(
                id="plugins",
                label="Plugins",
                kind="category",
                children=[
                    SelectionNode(
                        id="cpu",
                        label="CPU",
                        kind="category",
                        children=[
                            SelectionNode(
                                id="stress_ng",
                                label="stress-ng",
                                kind="plugin",
                            ),
                            SelectionNode(id="hpl", label="HPL", kind="plugin"),
                        ],
                    ),
                    SelectionNode(
                        id="io",
                        label="IO",
                        kind="category",
                        children=[SelectionNode(id="fio", label="fio", kind="plugin")],
                    ),
                ],
            ),
            SelectionNode(
                id="hosts",
                label="Hosts",
                kind="category",
                children=[SelectionNode(id="local", label="localhost", kind="host")],
            ),
        ],
    )


def test_headless_hierarchical_picker_defaults_to_first_leaf():
    ui = HeadlessUI()
    root = _sample_tree()

    picked = ui.hierarchical_picker.pick_one(root, title="Pick")
    assert picked is not None
    assert picked.id == "stress_ng"


def test_headless_hierarchical_picker_selects_by_path_ids():
    ui = HeadlessUI(next_hierarchical_pick_path=["plugins", "io", "fio"])
    root = _sample_tree()

    picked = ui.hierarchical_picker.pick_one(root, title="Pick")
    assert picked is not None
    assert picked.id == "fio"


def test_headless_hierarchical_picker_path_can_include_root_id():
    ui = HeadlessUI(next_hierarchical_pick_path=["root", "hosts", "local"])
    root = _sample_tree()

    picked = ui.hierarchical_picker.pick_one(root, title="Pick")
    assert picked is not None
    assert picked.id == "local"


def test_headless_hierarchical_picker_path_to_non_leaf_returns_first_leaf_below():
    ui = HeadlessUI(next_hierarchical_pick_path=["plugins", "cpu"])
    root = _sample_tree()

    picked = ui.hierarchical_picker.pick_one(root, title="Pick")
    assert picked is not None
    assert picked.id == "stress_ng"


def test_headless_hierarchical_picker_invalid_path_returns_none():
    ui = HeadlessUI(next_hierarchical_pick_path=["plugins", "missing"])
    root = _sample_tree()

    picked = ui.hierarchical_picker.pick_one(root, title="Pick")
    assert picked is None

