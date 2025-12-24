from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCENARIO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = SCENARIO_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from controller_stop_runner import run_controller  # type: ignore


@pytest.mark.parametrize(
    "stop_at,expected",
    [
        (None, {"success": True, "setup": True, "run_done": True, "teardown": True}),
        ("setup", {"teardown": True}),
        ("run", {"setup": True, "teardown": True}),
        ("teardown", {"setup": True, "teardown": True}),
    ],
)
def test_controller_stop_scenarios(tmp_path: Path, stop_at, expected):
    markers = run_controller(stop_at)

    for key, val in expected.items():
        assert markers.get(key) == val, f"Expected {key}={val} for stop_at={stop_at}, got {markers}"
