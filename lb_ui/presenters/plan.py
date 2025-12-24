"""Presenter for Run Plans."""

from __future__ import annotations

from typing import List, Any, Dict
from lb_ui.ui.system.models import TableModel


def build_run_plan_table(plan: List[Dict[str, Any]]) -> TableModel:
    """Transform a list of plan items into a TableModel."""
    rows = [
        [
            item["name"],
            item["plugin"],
            item["intensity"],
            item["details"],
            str(item.get("repetitions", "")),
            item["status"],
        ]
        for item in plan
    ]
    return TableModel(
        title="Run Plan",
        columns=["Workload", "Plugin", "Intensity", "Configuration", "Repetitions", "Status"],
        rows=rows,
    )
