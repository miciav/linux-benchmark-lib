"""Tests for LB_EVENT extraction and journal updates."""

import pytest

from lb_controller.journal import LogSink, RunJournal, RunStatus
from lb_app.services.run_service import _extract_lb_event_data
from lb_runner.events import RunEvent

pytestmark = pytest.mark.unit_controller


def test_extract_lb_event_data_handles_noise():
    line = 'TASK [debug] ********************************************************\nok: [localhost] => {"msg": "LB_EVENT {\\"run_id\\":\\"run-1\\",\\"host\\":\\"h1\\",\\"workload\\":\\"w\\",\\"repetition\\":1,\\"total_repetitions\\":3,\\"status\\":\\"running\\"}"}'
    data = _extract_lb_event_data(line, token="LB_EVENT")
    assert data is not None
    assert data["run_id"] == "run-1"
    assert data["status"] == "running"
    assert data["workload"] == "w"
    assert data["repetition"] == 1


def test_update_local_journal_sets_status(tmp_path):
    journal = RunJournal.initialize(
        "run-1",
        config=type("Cfg", (), {"remote_hosts": [type("H", (), {"name": "h1"})], "repetitions": 2, "workloads": {"w": {}}}),  # type: ignore
        test_types=["w"],
    )
    journal_path = tmp_path / "journal.json"
    journal.save(journal_path)

    event = RunEvent(
        run_id="run-1",
        host="h1",
        workload="w",
        repetition=1,
        total_repetitions=2,
        status="done",
        timestamp=0.0,
    )
    sink = LogSink(journal, journal_path)
    sink.emit(event)

    saved = RunJournal.load(journal_path)
    task = saved.get_task("h1", "w", 1)
    assert task is not None
    assert task.status == RunStatus.COMPLETED
