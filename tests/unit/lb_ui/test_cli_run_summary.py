import pytest

from lb_ui.api import build_journal_summary
from lb_controller.api import RunJournal, RunStatus, TaskState

pytestmark = [pytest.mark.unit_ui, pytest.mark.unit_ui]



def test_build_journal_summary_collapses_repetitions():
    journal = RunJournal(run_id="r1")
    journal.metadata["repetitions"] = 3
    journal.tasks = {
        "h::w::1": TaskState(host="h", workload="w", repetition=1, status=RunStatus.COMPLETED),
        "h::w::2": TaskState(host="h", workload="w", repetition=2, status=RunStatus.RUNNING, current_action="Doing"),
    }

    columns, rows = build_journal_summary(journal)

    assert columns == ["Host", "Workload", "Run", "Last Action"]
    assert rows == [["h", "w", "running\n1/3", "Doing"]]
