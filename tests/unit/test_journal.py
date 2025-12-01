"""Tests for the run journal data model."""

from pathlib import Path

import pytest

from linux_benchmark_lib.benchmark_config import BenchmarkConfig, RemoteHostConfig, WorkloadConfig
from linux_benchmark_lib.journal import RunJournal, RunStatus


def _base_config() -> BenchmarkConfig:
    cfg = BenchmarkConfig(
        remote_hosts=[RemoteHostConfig(name="node1", address="127.0.0.1")],
    )
    cfg.workloads = {"stress_ng": WorkloadConfig(plugin="stress_ng")}
    return cfg


def test_journal_initialize_and_update(tmp_path: Path):
    """Journal should track per-host, per-repetition status."""
    cfg = _base_config()
    journal = RunJournal.initialize("run-123", cfg, ["stress_ng"])

    # default to pending for every combination
    assert len(journal.tasks) == cfg.repetitions
    for task in journal.tasks.values():
        assert task.status == RunStatus.PENDING

    journal.update_task("node1", "stress_ng", 1, RunStatus.RUNNING, action="start")
    journal_path = tmp_path / "run_journal.json"
    journal.save(journal_path)

    loaded = RunJournal.load(journal_path, config=cfg)
    task = loaded.get_task("node1", "stress_ng", 1)
    assert task.status == RunStatus.RUNNING
    assert task.current_action == "start"


def test_journal_load_rejects_config_mismatch(tmp_path: Path):
    """Loading with a different config should fail to prevent accidental resumes."""
    cfg = _base_config()
    journal = RunJournal.initialize("run-123", cfg, ["stress_ng"])
    journal_path = tmp_path / "run_journal.json"
    journal.save(journal_path)

    altered = _base_config()
    altered.repetitions = 2
    with pytest.raises(ValueError):
        RunJournal.load(journal_path, config=altered)
