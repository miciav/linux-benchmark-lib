"""Presenter for Doctor Reports."""

from __future__ import annotations

from typing import List
from lb_app.api import DoctorReport
from lb_ui.ui.system.models import TableModel


def build_doctor_tables(report: DoctorReport) -> List[TableModel]:
    """Transform a DoctorReport into a list of TableModels."""
    tables = []
    for group in report.groups:
        rows = [[item.label, "✓" if item.ok else "✗"] for item in group.items]
        tables.append(
            TableModel(
                title=group.title,
                columns=["Item", "Status"],
                rows=rows,
            )
        )
    return tables


def render_doctor_report(ui, report: DoctorReport) -> bool:
    """
    Render a doctor report to the provided UI.

    Returns True when all checks passed.
    """
    for table in build_doctor_tables(report):
        ui.tables.show(table)

    for msg in report.info_messages:
        ui.present.info(msg)

    if report.total_failures > 0:
        ui.present.error(f"Found {report.total_failures} failures.")
        return False

    ui.present.success("All checks passed.")
    return True
