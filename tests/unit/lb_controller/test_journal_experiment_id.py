import re
from pathlib import Path

import pytest

from lb_controller.services.journal import RunJournal
from lb_controller.services.paths import generate_experiment_id
from lb_runner.api import BenchmarkConfig

pytestmark = pytest.mark.unit_controller


def test_generated_id_has_its_own_namespace() -> None:
    assert re.fullmatch(r"exp-\d{8}-\d{6}", generate_experiment_id())


def test_metadata_records_the_configured_id() -> None:
    journal = RunJournal.initialize(
        "run-1", BenchmarkConfig(experiment_id="tuning"), []
    )
    assert journal.metadata["experiment_id"] == "tuning"


def test_metadata_generates_an_id_when_none_is_configured() -> None:
    journal = RunJournal.initialize("run-1", BenchmarkConfig(), [])
    assert re.fullmatch(r"exp-\d{8}-\d{6}", journal.metadata["experiment_id"])


def test_experiment_id_does_not_change_the_config_hash() -> None:
    a = RunJournal.initialize("run-1", BenchmarkConfig(), [])
    b = RunJournal.initialize("run-1", BenchmarkConfig(experiment_id="x"), [])
    assert a.metadata["config_hash"] == b.metadata["config_hash"]


def test_a_generated_id_run_resumes_with_its_original_config(tmp_path: Path) -> None:
    journal = RunJournal.initialize("run-1", BenchmarkConfig(), [])
    path = tmp_path / "run_journal.json"
    journal.save(path)
    loaded = RunJournal.load(path, config=BenchmarkConfig())
    assert loaded.metadata["experiment_id"] == journal.metadata["experiment_id"]


def test_resume_rejects_a_different_experiment(tmp_path: Path) -> None:
    journal = RunJournal.initialize("run-1", BenchmarkConfig(experiment_id="a"), [])
    path = tmp_path / "run_journal.json"
    journal.save(path)
    with pytest.raises(ValueError, match="run-1 belongs to experiment 'a'"):
        RunJournal.load(path, config=BenchmarkConfig(experiment_id="b"))


def test_resume_of_a_journal_without_id_accepts_a_configured_one(
    tmp_path: Path,
) -> None:
    journal = RunJournal.initialize("run-1", BenchmarkConfig(), [])
    del journal.metadata["experiment_id"]  # a journal from before this change
    path = tmp_path / "run_journal.json"
    journal.save(path)
    RunJournal.load(path, config=BenchmarkConfig(experiment_id="b"))
