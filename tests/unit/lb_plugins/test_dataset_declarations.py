"""Every plugin must declare every file and every numeric column it exports.

Runs each plugin's export on real outputs captured from Multipass runs
(tests/fixtures/plugin_outputs), then checks its describe_datasets().
"""

import json
import re
import shutil
from pathlib import Path

import pandas as pd
import pytest

from lb_common.api import DatasetDescriptor, plan_wide
from lb_plugins.api import create_registry

pytestmark = pytest.mark.unit_plugins

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "plugin_outputs"

# Workloads whose declarations are complete. Later tasks extend this list.
DECLARED: list[str] = ["sysbench"]


def _export(tmp_path: Path, workload: str) -> Path:
    work = tmp_path / workload
    shutil.copytree(FIXTURES / workload, work)
    results = json.loads((work / f"{workload}_results.json").read_text())
    plugin = create_registry().get(workload)
    plugin.export_results_to_csv(results, work, "fixture-run", workload)
    return work


def _covered(d: DatasetDescriptor, frame: pd.DataFrame) -> set[str]:
    covered = {*d.keys, "repetition"}
    covered |= {c for c in frame.columns if any(re.fullmatch(p, c) for p in d.exclude)}
    if d.shape == "wide":
        plan = plan_wide(d, list(frame.columns))
        assert not plan.unmatched_specs, f"{d.name}: {plan.unmatched_specs}"
        for metric in plan.metrics:
            assert pd.api.types.is_numeric_dtype(frame[metric.column]), (
                f"{d.name}: metric column {metric.column} is not numeric"
            )
        covered |= {m.column for m in plan.metrics}
    else:
        covered |= {v.column for v in d.value_columns}
        covered |= {c for c in (d.value_column,) if c}
    return covered


@pytest.mark.parametrize("workload", DECLARED)
def test_plugin_declares_every_file_and_numeric_column(
    tmp_path: Path, workload: str
) -> None:
    work = _export(tmp_path, workload)
    descriptors = create_registry().get(workload).describe_datasets(work, workload)
    declared_files: set[Path] = set()
    for d in descriptors:
        files = sorted(work.glob(d.path))
        assert files, f"{d.name}: {d.path!r} matches no file"
        declared_files |= {f.relative_to(work) for f in files}
        if d.target_table != "results":
            continue
        for path in files:
            frame = pd.read_csv(path)
            numeric = {
                c for c in frame.columns if pd.api.types.is_numeric_dtype(frame[c])
            }
            missing = numeric - _covered(d, frame)
            assert not missing, f"{path.name}: undeclared numeric {sorted(missing)}"
    # Collector files under rep*/ are the runner's, not the plugin's.
    exported = {
        p.relative_to(work)
        for p in work.rglob("*.csv")
        if not p.relative_to(work).parts[0].startswith("rep")
    }
    undeclared = sorted(exported - declared_files)
    assert not undeclared, f"undeclared: {undeclared}"
