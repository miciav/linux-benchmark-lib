import json
import shutil
from pathlib import Path

import pytest

from lb_app.api import RunCatalogService, load_experiment
from lb_plugins.api import create_registry
from lb_runner.api import write_host_manifest, write_workload_manifest

pytestmark = pytest.mark.unit_analytics

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "plugin_outputs"


def _collected_run(root: Path, run_id: str, experiment: str, workload: str) -> None:
    host_dir = root / run_id / "h1"
    host_dir.mkdir(parents=True)
    shutil.copy(FIXTURES / "_host" / "system_info.csv", host_dir)
    write_host_manifest(host_dir)
    work = host_dir / workload
    shutil.copytree(FIXTURES / workload, work)
    plugin = create_registry().get(workload)
    results = json.loads((work / f"{workload}_results.json").read_text())
    plugin.export_results_to_csv(results, work, run_id, workload)
    write_workload_manifest(plugin, work, workload)
    journal = {
        "run_id": run_id,
        "metadata": {
            "created_at": "2026-10-09T10:00:00",
            "experiment_id": experiment,
        },
        "tasks": [{"host": "h1", "workload": workload}],
    }
    (root / run_id / "run_journal.json").write_text(json.dumps(journal))


def test_an_experiment_loads_only_its_own_runs(tmp_path: Path) -> None:
    root = tmp_path / "benchmark_results"
    _collected_run(root, "run-1", "tuning", "fio")
    _collected_run(root, "run-2", "tuning", "stress_ng")
    _collected_run(root, "run-3", "other", "dd")
    experiment = RunCatalogService(root).get_experiment("tuning")
    assert experiment is not None
    data = load_experiment(experiment.runs)
    assert set(data.runs.run_id) == {"run-1", "run-2"}
    assert set(data.runs.experiment_id) == {"tuning"}
    assert set(data.results.workload) == {"fio", "stress_ng"}
