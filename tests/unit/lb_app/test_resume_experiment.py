import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from lb_app.api import RunJournal
from lb_app.services.run_journal import load_resume_journal
from lb_app.services.run_types import RunContext
from lb_runner.api import BenchmarkConfig

pytestmark = pytest.mark.unit_ui


def test_resume_keeps_the_journal_experiment_and_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    started = BenchmarkConfig(output_dir=tmp_path, experiment_id="alpha")
    journal = RunJournal.initialize("run-1", started, [])
    (tmp_path / "run-1").mkdir()
    journal.save(tmp_path / "run-1" / "run_journal.json")
    context = RunContext(
        config=BenchmarkConfig(output_dir=tmp_path, experiment_id="beta"),
        target_tests=[],
        registry=MagicMock(),
        resume_from="run-1",
    )
    with caplog.at_level(logging.WARNING):
        resumed, _, _ = load_resume_journal(context, None)
    assert resumed.metadata["experiment_id"] == "alpha"
    assert "alpha" in caplog.text and "beta" in caplog.text
