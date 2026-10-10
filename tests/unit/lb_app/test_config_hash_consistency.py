import pytest

from lb_app.api import RunJournal
from lb_app.services.run_journal import hash_config
from lb_runner.api import BenchmarkConfig

pytestmark = pytest.mark.unit_ui


@pytest.mark.parametrize("experiment_id", [None, "tuning"])
def test_resume_and_journal_hash_a_config_the_same_way(
    experiment_id: str | None,
) -> None:
    cfg = BenchmarkConfig(experiment_id=experiment_id)
    journal = RunJournal.initialize("run-1", cfg, [])
    assert hash_config(cfg) == journal.metadata["config_hash"]
