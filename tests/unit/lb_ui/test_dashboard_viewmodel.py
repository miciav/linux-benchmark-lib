from types import SimpleNamespace

import pytest

from lb_app.api import RunJournal, RunStatus, TaskState, build_dashboard_viewmodel
from lb_ui.presenters.dashboard import event_status_line

pytestmark = pytest.mark.unit_ui


def _journal_with_tasks() -> RunJournal:
    cfg = SimpleNamespace(
        remote_hosts=[SimpleNamespace(name="localhost")],
        repetitions=2,
        workloads={"w": {}},
    )
    journal = RunJournal.initialize("run-1", cfg, ["w"])
    task1 = journal.get_task("localhost", "w", 1)
    task2 = journal.get_task("localhost", "w", 2)
    assert isinstance(task1, TaskState)
    assert isinstance(task2, TaskState)
    task1.status = RunStatus.COMPLETED
    task1.finished_at = 10.0
    task1.duration_seconds = 4.25
    task2.status = RunStatus.RUNNING
    task2.current_action = "Doing work"
    return journal


def test_build_dashboard_viewmodel_rows() -> None:
    journal = _journal_with_tasks()
    plan = [{"name": "w", "plugin": "stress_ng", "intensity": "low"}]

    viewmodel = build_dashboard_viewmodel(plan, journal)
    snapshot = viewmodel.snapshot()

    assert snapshot.run_id == "run-1"
    assert snapshot.row_count == 1
    assert snapshot.status_summary.total == 2
    assert snapshot.status_summary.running == 1
    row = snapshot.rows[0]
    assert row.host == "localhost"
    assert row.workload == "w"
    assert row.intensity == "low"
    assert row.status == "running"
    assert row.progress == "2/2"
    assert row.current_action == "Doing work"
    assert row.last_rep_time == "4.2s"


def test_event_status_line_formats_age() -> None:
    line = event_status_line("stdout", 10.0, now=12.3)
    assert "stdout" in line
    assert "2.3s ago" in line
