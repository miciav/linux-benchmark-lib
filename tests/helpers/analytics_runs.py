"""Build collected run folders from the real plugin fixtures."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from lb_plugins.api import create_registry
from lb_runner.api import write_host_manifest, write_workload_manifest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "plugin_outputs"


def collected_run(
    root: Path,
    run_id: str,
    experiment: str | None,
    workload: str,
    created_at: str = "2026-10-09T10:00:00",
    host: str = "h1",
) -> None:
    """Lay out a run as the controller leaves it after collection."""
    host_dir = root / run_id / host
    host_dir.mkdir(parents=True)
    shutil.copy(FIXTURES / "_host" / "system_info.csv", host_dir)
    write_host_manifest(host_dir)
    work = host_dir / workload
    shutil.copytree(FIXTURES / workload, work)
    plugin = create_registry().get(workload)
    results = json.loads((work / f"{workload}_results.json").read_text())
    plugin.export_results_to_csv(results, work, run_id, workload)
    write_workload_manifest(plugin, work, workload)
    metadata: dict[str, str] = {"created_at": created_at}
    if experiment is not None:
        metadata["experiment_id"] = experiment
    journal = {
        "run_id": run_id,
        "metadata": metadata,
        "tasks": [{"host": host, "workload": workload}],
    }
    (root / run_id / "run_journal.json").write_text(json.dumps(journal))
