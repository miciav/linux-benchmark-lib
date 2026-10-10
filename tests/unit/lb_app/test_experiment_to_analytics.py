from pathlib import Path

import pytest

from lb_app.api import RunCatalogService, load_experiment
from tests.helpers.analytics_runs import collected_run

pytestmark = pytest.mark.unit_analytics


def test_an_experiment_loads_only_its_own_runs(tmp_path: Path) -> None:
    root = tmp_path / "benchmark_results"
    collected_run(root, "run-1", "tuning", "fio")
    collected_run(root, "run-2", "tuning", "stress_ng")
    collected_run(root, "run-3", "other", "dd")
    experiment = RunCatalogService(root).get_experiment("tuning")
    assert experiment is not None
    data = load_experiment(experiment.runs)
    assert set(data.runs.run_id) == {"run-1", "run-2"}
    assert set(data.runs.experiment_id) == {"tuning"}
    assert set(data.results.workload) == {"fio", "stress_ng"}
