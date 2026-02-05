import pytest

from lb_ui.api import build_run_plan_table

pytestmark = [pytest.mark.unit_ui, pytest.mark.unit_ui]


def test_build_run_plan_table_docker_mode():
    """Ensure plan presenter includes workload and engine details."""
    plan = [
        {
            "name": "stress_ng",
            "plugin": "stress_ng",
            "intensity": "default",
            "details": "Docker engine",
            "repetitions": 1,
            "status": "ready",
        }
    ]

    table = build_run_plan_table(plan)

    assert table.columns == [
        "Workload",
        "Plugin",
        "Intensity",
        "Configuration",
        "Repetitions",
        "Status",
    ]
    assert table.rows == [
        ["stress_ng", "stress_ng", "default", "Docker engine", "1", "ready"]
    ]
