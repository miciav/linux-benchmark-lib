from pathlib import Path
from unittest.mock import MagicMock

import pytest

from lb_app.api import RunJournal
from lb_runner.api import BenchmarkConfig
from lb_ui.cli.commands.run_helpers import print_run_journal_summary

pytestmark = pytest.mark.unit_ui


def test_summary_tells_how_to_add_runs_to_the_experiment(tmp_path: Path) -> None:
    journal = RunJournal.initialize("run-1", BenchmarkConfig(experiment_id="io"), [])
    path = tmp_path / "run_journal.json"
    journal.save(path)
    ctx = MagicMock()
    print_run_journal_summary(ctx, path)
    messages = " ".join(str(c.args[0]) for c in ctx.ui.present.info.call_args_list)
    assert "Experiment: io" in messages
    assert "lb run --experiment io" in messages
