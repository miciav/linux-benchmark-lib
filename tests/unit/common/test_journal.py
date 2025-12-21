"""Tests for the run journal data model."""

from pathlib import Path

import pytest

from lb_runner.benchmark_config import BenchmarkConfig, RemoteHostConfig, WorkloadConfig
from lb_controller.api import RunJournal, RunStatus

pytestmark = pytest.mark.unit_controller



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
    task_after_update = journal.get_task("node1", "stress_ng", 1)
    assert task_after_update is not None
    assert task_after_update.started_at is not None
    assert task_after_update.duration_seconds is None
    journal_path = tmp_path / "run_journal.json"
    journal.save(journal_path)

    loaded = RunJournal.load(journal_path, config=cfg)
    task = loaded.get_task("node1", "stress_ng", 1)
    assert task.status == RunStatus.RUNNING
    assert task.current_action == "start"
    assert task.started_at is not None
    assert task.duration_seconds is None


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


def test_journal_initializes_local_host_when_none():
    """Journal should include a localhost placeholder when no remote hosts are defined."""
    cfg = BenchmarkConfig()
    cfg.workloads = {"stress_ng": WorkloadConfig(plugin="stress_ng")}
    journal = RunJournal.initialize("run-local", cfg, ["stress_ng"])
    assert any(task.host == "localhost" for task in journal.tasks.values())
    assert len(journal.tasks) == cfg.repetitions


def test_journal_rehydrate_config_from_dump(tmp_path: Path):
    """Journal should carry enough config to resume without external config files."""
    cfg = _base_config()
    journal = RunJournal.initialize("run-456", cfg, ["stress_ng"])
    journal_path = tmp_path / "run_journal.json"
    journal.save(journal_path)

    loaded = RunJournal.load(journal_path)
    recovered = loaded.rehydrate_config()
    assert recovered is not None
    assert recovered.remote_hosts[0].name == cfg.remote_hosts[0].name
    assert "stress_ng" in recovered.workloads
