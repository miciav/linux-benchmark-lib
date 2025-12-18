import pytest

from lb_ui.cli import _build_journal_summary
from lb_controller.journal import RunJournal, RunStatus, TaskState

pytestmark = [pytest.mark.ui, pytest.mark.ui]



def test_build_journal_summary_collapses_repetitions():
    journal = RunJournal(run_id="r1")
    journal.metadata["repetitions"] = 3
    journal.tasks = {
        "h::w::1": TaskState(host="h", workload="w", repetition=1, status=RunStatus.COMPLETED),
        "h::w::2": TaskState(host="h", workload="w", repetition=2, status=RunStatus.RUNNING, current_action="Doing"),
    }

    columns, rows = _build_journal_summary(journal)

    assert columns == ["Host", "Workload", "Run", "Last Action"]
    assert rows == [["h", "w", "running\n1/3", "Doing"]]
