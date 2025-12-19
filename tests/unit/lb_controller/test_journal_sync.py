from pathlib import Path

from lb_controller.journal_sync import backfill_timings_from_results
from lb_controller.journal import RunJournal, RunStatus
from lb_runner.benchmark_config import BenchmarkConfig, WorkloadConfig, RemoteHostConfig


def _journal_for(workload: str = "stress_ng") -> tuple[RunJournal, BenchmarkConfig]:
    cfg = BenchmarkConfig()
    cfg.workloads[workload] = WorkloadConfig(plugin=workload, enabled=True)
    cfg.remote_hosts = [RemoteHostConfig(name="host1", address="1.2.3.4")]
    journal = RunJournal.initialize("run-1", cfg, [workload])
    return journal, cfg


def test_backfill_marks_completed_and_sets_duration(tmp_path: Path):
    journal, _ = _journal_for()
    results = tmp_path / "host1"
    results.mkdir()
    payload = [
        {
            "repetition": 1,
            "start_time": "2024-01-01T00:00:00",
            "end_time": "2024-01-01T00:00:10",
            "duration_seconds": 10.0,
            "generator_result": {"returncode": 0},
        }
    ]
    (results / "stress_ng_results.json").write_text(json_dumps(payload))

    backfill_timings_from_results(
        journal,
        tmp_path / "journal.json",
        [RemoteHostConfig(name="host1", address="1.2.3.4")],
        "stress_ng",
        {"host1": results},
    )

    task = journal.get_task("host1", "stress_ng", 1)
    assert task.status == RunStatus.COMPLETED
    assert task.duration_seconds == 10.0


def test_backfill_marks_failed_on_error(tmp_path: Path):
    journal, _ = _journal_for()
    results = tmp_path / "host1"
    results.mkdir()
    payload = [
        {
            "repetition": 1,
            "generator_result": {"error": "boom", "returncode": 2, "command": "cmd"},
        }
    ]
    (results / "stress_ng_results.json").write_text(json_dumps(payload))

    backfill_timings_from_results(
        journal,
        tmp_path / "journal.json",
        [RemoteHostConfig(name="host1", address="1.2.3.4")],
        "stress_ng",
        {"host1": results},
    )

    task = journal.get_task("host1", "stress_ng", 1)
    assert task.status == RunStatus.FAILED
    assert "boom" in task.error
    assert "returncode=2" in task.error
    assert "cmd=cmd" in task.error


def json_dumps(payload):
    # Local helper to avoid importing json in multiple tests
    import json

    return json.dumps(payload)
