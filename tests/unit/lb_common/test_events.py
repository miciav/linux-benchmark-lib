from types import SimpleNamespace

import pytest

from lb_runner.api import RunEvent
from lb_controller.api import LogSink, RunJournal, RunStatus

pytestmark = pytest.mark.unit_controller


def test_log_sink_updates_journal_and_log(tmp_path):
    # Minimal journal stub
    journal = RunJournal(run_id="run-1")
    # Seed a task so update_task finds it
    seeded = RunJournal.initialize(
        "run-1",
        SimpleNamespace(
            remote_hosts=[SimpleNamespace(name="localhost")],
            repetitions=1,
            workloads={"geekbench": SimpleNamespace()},
            plugin_settings={},
            collectors=None,
        ),
        ["geekbench"],
    )
    journal.tasks = seeded.tasks

    journal_path = tmp_path / "run_journal.json"
    log_path = tmp_path / "run.log"
    sink = LogSink(journal, journal_path, log_path)

    event = RunEvent(
        run_id="run-1",
        host="localhost",
        workload="geekbench",
        repetition=1,
        total_repetitions=3,
        status="running",
        message="",
        timestamp=0.0,
    )

    sink.emit(event)

    # Journal should be saved and updated
    assert journal_path.exists()
    saved = RunJournal.load(journal_path)
    task = saved.get_task("localhost", "geekbench", 1)
    assert task.status == RunStatus.RUNNING

    # Log should contain a line
    assert log_path.exists()
    assert "geekbench" in log_path.read_text()

    sink.close()


def test_log_sink_records_error_type(tmp_path):
    journal = RunJournal(run_id="run-2")
    seeded = RunJournal.initialize(
        "run-2",
        SimpleNamespace(
            remote_hosts=[SimpleNamespace(name="localhost")],
            repetitions=1,
            workloads={"geekbench": SimpleNamespace()},
            plugin_settings={},
            collectors=None,
        ),
        ["geekbench"],
    )
    journal.tasks = seeded.tasks
    journal_path = tmp_path / "run_journal.json"
    sink = LogSink(journal, journal_path)

    event = RunEvent(
        run_id="run-2",
        host="localhost",
        workload="geekbench",
        repetition=1,
        total_repetitions=1,
        status="failed",
        message="boom",
        error_type="WorkloadError",
        error_context={"detail": "x"},
    )

    sink.emit(event)

    saved = RunJournal.load(journal_path)
    task = saved.get_task("localhost", "geekbench", 1)
    assert task.error_type == "WorkloadError"
    assert task.error_context == {"detail": "x"}
