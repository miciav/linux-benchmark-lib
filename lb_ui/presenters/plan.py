"""Presenter for Run Plans."""

from __future__ import annotations

from typing import Any

from lb_app.api import plan_rows
from lb_ui.tui.system.models import TableModel


def build_run_plan_table(plan: list[dict[str, Any]]) -> TableModel:
    """Transform a list of plan items into a TableModel."""
    rows = [
        [
            name,
            plugin,
            intensity,
            details,
            str(repetitions),
            status,
        ]
        for name, plugin, intensity, details, repetitions, status in plan_rows(plan)
    ]
    return TableModel(
        title="Run Plan",
        columns=[
            "Workload",
            "Plugin",
            "Intensity",
            "Configuration",
            "Repetitions",
            "Status",
        ],
        rows=rows,
    )
