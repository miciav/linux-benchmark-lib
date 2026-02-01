"""Presenter for Run Journals."""

from __future__ import annotations

from lb_app.api import RunJournal, journal_rows
from lb_ui.tui.system.models import TableModel


def build_journal_summary(journal: RunJournal) -> tuple[list[str], list[list[str]]]:
    """
    Summarize run progress by host/workload collapsing repetitions.

    Returns column headers and row data for a compact table (without TableModel).
    """
    return journal_rows(journal)


def build_journal_table(journal: RunJournal) -> TableModel:
    """Transform a RunJournal into a TableModel."""
    columns, rows = journal_rows(journal)
    return TableModel(
        title=f"Run Journal (ID: {journal.run_id})",
        columns=columns,
        rows=rows,
    )
