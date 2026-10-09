# Analytics Dataset Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every producer declares its datasets in a `datasets.json` manifest, and `lb_analytics.load_experiment(runs)` turns all declared files of a set of runs into five tidy pandas tables (`runs`, `host_info`, `repetitions`, `results`, `samples`) plus a load report, writable as Parquet.

**Architecture:** The descriptor model and the column-planning logic live in `lb_common` (the only package both producers and `lb_analytics` may import). Plugins declare their files through a new `WorkloadPlugin.describe_datasets()`; the runner writes the manifests next to the data on the remote host, so they travel with the existing collection. `lb_analytics` reads manifests only and never imports plugins.

**Tech Stack:** Python 3.12, pydantic v2 (descriptor model), pandas ≥ 2, pyarrow ≥ 17 (Parquet), pytest.

**Spec:** `docs/superpowers/specs/2026-10-09-analytics-dataset-unification-design.md`

## Global Constraints

- Manifest file name: `datasets.json`; manifest `version`: `1`.
- `lb_analytics` may import only `lb_common` among first-party packages (import-linter contract "lb_analytics isolation").
- Cross-package imports go through `lb_common.api`, `lb_plugins.api`, `lb_runner.api`, `lb_analytics.api` (ruff TID251 + `scripts/check_api_imports.py`).
- Parquet files: `runs.parquet`, `host_info.parquet`, `repetitions.parquet`, `results.parquet`, `samples.parquet`, plus `load_report.json`.
- `pyarrow>=17.0.0` goes into the `controller` extra.
- Runs without manifests are not supported: they are reported as not loadable, never guessed.
- Metrics are numeric; units are declared, never inferred; only declared files and columns are loaded.
- Style: ruff (88 cols), basedpyright standard; test markers `unit_common`, `unit_plugins`, `unit_runner`, `unit_analytics`.
- Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

- A metric column holding a non-numeric value (e.g. a stray `"fast"`; note `"N/A"`, `"nan"` and empty cells are pandas NA tokens and count as missing, not as errors): the whole dataset is rejected with file, column and count, no partial rows — tested in Task 7.
- A declared file that is missing on disk: that dataset errors, every other dataset of the run still loads — tested in Task 8.
- A local run (no host directory level): manifests are found and attributed to host `localhost` — tested in Task 8.
- A run directory without `run_journal.json`: the run still loads, its `runs` row has empty metadata and the report warns — tested in Task 8.
- Datasets with different dimensions concatenated into one `results` table: absent dimensions are real nulls (`<NA>`), not the string `"nan"` — tested in Task 8.

---

### Task 0: Branch and baseline

**Files:** none created.

- [ ] **Step 1: Create the feature branch**

```bash
git switch -c analytics-dataset-unification
```

- [ ] **Step 2: Commit the pending plugin-verification fixes on their own**

The working tree still holds the fixes from the 2026-10-08 Multipass verification (25 files) and the spec. Commit them separately so this plan's commits stay reviewable. Only do this if the user approved committing them; otherwise stop and ask.

```bash
git add lb_controller lb_plugins tests docs/superpowers/specs
git commit -m "Fix plugin data collection and conversion found by Multipass verification

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 3: Confirm a green baseline**

Run: `uv run pytest -q -p no:cacheprovider tests/unit`
Expected: exit code 0.

---

### Task 1: Dataset manifest model in `lb_common`

**Files:**
- Create: `lb_common/models/datasets.py`
- Modify: `lb_common/api.py` (imports and `__all__`)
- Test: `tests/unit/lb_common/test_datasets.py`

**Interfaces:**
- Produces: `MANIFEST_FILENAME: str`, `MetricSpec`, `ValueColumn`, `DatasetDescriptor` (with property `target_table`), `DatasetManifest`, `write_manifest(directory: Path, manifest: DatasetManifest) -> Path`, `read_manifest(directory: Path) -> DatasetManifest`, `MetricColumn` (frozen dataclass: `column, metric, dims, unit, unit_column`), `WidePlan` (dataclass: `metrics, unmatched_specs, ignored`), `plan_wide(descriptor: DatasetDescriptor, columns: Sequence[str]) -> WidePlan`. All re-exported from `lb_common.api`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/lb_common/test_datasets.py
from pathlib import Path

import pytest
from pydantic import ValidationError

from lb_common.api import (
    DatasetDescriptor,
    DatasetManifest,
    MetricSpec,
    ValueColumn,
    plan_wide,
    read_manifest,
    write_manifest,
)

pytestmark = pytest.mark.unit_common


def _wide(**kwargs) -> DatasetDescriptor:
    return DatasetDescriptor(name="d", path="d.csv", shape="wide", **kwargs)


def test_pattern_must_name_a_metric_group() -> None:
    with pytest.raises(ValidationError, match="metric"):
        MetricSpec(pattern=r"^gen_(?P<x>.+)$")


def test_metric_needs_exactly_one_of_column_or_pattern() -> None:
    with pytest.raises(ValidationError):
        MetricSpec()
    with pytest.raises(ValidationError):
        MetricSpec(column="a", pattern=r"(?P<metric>a)")


def test_timeseries_requires_time_column() -> None:
    with pytest.raises(ValidationError, match="time_column"):
        DatasetDescriptor(name="t", path="t.csv", shape="timeseries")


def test_long_requires_one_value_layout() -> None:
    with pytest.raises(ValidationError):
        DatasetDescriptor(name="l", path="l.csv", shape="long")
    DatasetDescriptor(
        name="l", path="l.csv", shape="long", value_columns=[ValueColumn(column="v")]
    )
    DatasetDescriptor(
        name="l", path="l.csv", shape="long", metric_column="m", value_column="v"
    )


def test_host_info_long_needs_only_value_column() -> None:
    d = DatasetDescriptor(
        name="system_info",
        path="system_info.csv",
        shape="long",
        table="host_info",
        keys=["category", "name"],
        value_column="value",
    )
    assert d.target_table == "host_info"


def test_target_table_defaults_follow_shape() -> None:
    assert _wide().target_table == "results"
    ts = DatasetDescriptor(name="t", path="t.csv", shape="timeseries", time_column="ts")
    assert ts.target_table == "samples"


def test_manifest_round_trip(tmp_path: Path) -> None:
    manifest = DatasetManifest(
        workload="fio",
        plugin="fio",
        repetitions="fio_results.json",
        datasets=[_wide(metrics=[MetricSpec(column="read_iops", unit="IOPS")])],
    )
    path = write_manifest(tmp_path, manifest)
    assert path.name == "datasets.json"
    assert read_manifest(tmp_path) == manifest


def test_plan_wide_extracts_metric_and_dimensions() -> None:
    d = _wide(
        keys=["repetition"],
        metrics=[
            MetricSpec(
                pattern=r"^generator_(?P<stressor>.+?)_(?P<metric>bogo_ops)$",
                unit="ops",
            )
        ],
        exclude=["generator_stdout"],
    )
    plan = plan_wide(
        d, ["repetition", "generator_cpu_bogo_ops", "generator_stdout", "run_id"]
    )
    [metric] = plan.metrics
    assert (metric.column, metric.metric, metric.unit) == (
        "generator_cpu_bogo_ops",
        "bogo_ops",
        "ops",
    )
    assert metric.dims == {"stressor": "cpu"}
    assert plan.ignored == ["run_id"]
    assert plan.unmatched_specs == []


def test_plan_wide_resolves_unit_column_template_and_reports_unmatched() -> None:
    d = _wide(
        metrics=[
            MetricSpec(
                pattern=r"^g_(?P<test>.+)_(?P<metric>result)$",
                unit_column="g_{test}_unit",
            ),
            MetricSpec(column="missing", unit="s"),
        ]
    )
    plan = plan_wide(d, ["g_dhry_result", "g_dhry_unit"])
    assert plan.metrics[0].unit_column == "g_dhry_unit"
    assert plan.unmatched_specs == ["missing"]


def test_plan_wide_column_metric_uses_explicit_name() -> None:
    d = _wide(metrics=[MetricSpec(column="generator_x", name="x", unit="s")])
    assert plan_wide(d, ["generator_x"]).metrics[0].metric == "x"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest -q -p no:cacheprovider tests/unit/lb_common/test_datasets.py`
Expected: FAIL with `ImportError: cannot import name 'DatasetDescriptor' from 'lb_common.api'`.

- [ ] **Step 3: Implement the model**

```python
# lb_common/models/datasets.py
"""Dataset manifests: how producers declare the tables they write.

Workload plugins and the runner write a ``datasets.json`` next to their files;
``lb_analytics`` reads only these manifests. This module is the shared contract,
including the column planning both the loader and the plugin contract tests use.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MANIFEST_FILENAME = "datasets.json"

Shape = Literal["wide", "long", "timeseries"]
TargetTable = Literal["results", "samples", "host_info", "ignore"]


class MetricSpec(BaseModel):
    """One metric of a wide dataset: an exact column or a regex over columns."""

    model_config = ConfigDict(extra="forbid")

    column: str | None = None
    pattern: str | None = None
    name: str | None = None
    unit: str | None = None
    unit_column: str | None = None

    @model_validator(mode="after")
    def _check(self) -> MetricSpec:
        if (self.column is None) == (self.pattern is None):
            raise ValueError("a metric needs exactly one of 'column' or 'pattern'")
        if self.pattern is not None:
            if "metric" not in re.compile(self.pattern).groupindex:
                raise ValueError(f"pattern {self.pattern!r} needs a 'metric' group")
            if self.name is not None:
                raise ValueError("'name' applies to 'column' metrics only")
        if self.unit is not None and self.unit_column is not None:
            raise ValueError("use 'unit' or 'unit_column', not both")
        return self


class ValueColumn(BaseModel):
    """A measure column of a long dataset; the metric name is the column name."""

    model_config = ConfigDict(extra="forbid")

    column: str
    unit: str | None = None


class DatasetDescriptor(BaseModel):
    """Declaration of one dataset file (or glob of files)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    path: str
    shape: Shape
    table: TargetTable | None = None
    keys: list[str] = Field(default_factory=list)
    fixed: dict[str, str | int] = Field(default_factory=dict)
    metrics: list[MetricSpec] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    value_columns: list[ValueColumn] = Field(default_factory=list)
    metric_column: str | None = None
    value_column: str | None = None
    unit: str | None = None
    unit_column: str | None = None
    time_column: str | None = None

    @property
    def target_table(self) -> TargetTable:
        if self.table is not None:
            return self.table
        return "samples" if self.shape == "timeseries" else "results"

    @model_validator(mode="after")
    def _check_shape(self) -> DatasetDescriptor:
        for pattern in self.exclude:
            re.compile(pattern)
        if self.shape == "timeseries" and not self.time_column:
            raise ValueError(f"{self.name}: a timeseries needs 'time_column'")
        if self.shape == "long" and self.target_table == "host_info":
            if not self.value_column:
                raise ValueError(f"{self.name}: host_info needs 'value_column'")
        elif self.shape == "long" and self.target_table != "ignore":
            pair = self.metric_column is not None and self.value_column is not None
            if bool(self.value_columns) == pair:
                raise ValueError(
                    f"{self.name}: a long dataset needs 'value_columns' or "
                    "'metric_column' + 'value_column'"
                )
        return self


class DatasetManifest(BaseModel):
    """Content of one ``datasets.json``."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    workload: str | None = None
    plugin: str | None = None
    repetitions: str | None = None
    datasets: list[DatasetDescriptor] = Field(default_factory=list)


def write_manifest(directory: Path, manifest: DatasetManifest) -> Path:
    """Write ``datasets.json`` into ``directory`` and return its path."""
    path = directory / MANIFEST_FILENAME
    path.write_text(manifest.model_dump_json(indent=2, exclude_none=True))
    return path


def read_manifest(directory: Path) -> DatasetManifest:
    """Read and validate ``directory/datasets.json``."""
    text = (directory / MANIFEST_FILENAME).read_text()
    return DatasetManifest.model_validate_json(text)


@dataclass(frozen=True)
class MetricColumn:
    """A wide column resolved to a metric, its dimensions and its unit."""

    column: str
    metric: str
    dims: dict[str, str]
    unit: str | None
    unit_column: str | None


@dataclass
class WidePlan:
    """How the columns of a wide file map onto metrics."""

    metrics: list[MetricColumn] = field(default_factory=list)
    unmatched_specs: list[str] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)


def plan_wide(descriptor: DatasetDescriptor, columns: Sequence[str]) -> WidePlan:
    """Resolve which columns of a wide file are metrics, and how."""
    excluded = [re.compile(p) for p in descriptor.exclude]
    keys = {*descriptor.keys, "repetition"}

    def available(column: str) -> bool:
        return column not in keys and not any(p.fullmatch(column) for p in excluded)

    plan = WidePlan()
    claimed: set[str] = set()
    for spec in descriptor.metrics:
        matched = False
        for column in columns:
            if column in claimed or not available(column):
                continue
            resolved = _resolve(spec, column)
            if resolved is not None:
                plan.metrics.append(resolved)
                claimed.add(column)
                matched = True
        if not matched:
            plan.unmatched_specs.append(spec.column or spec.pattern or "")
    plan.ignored = [c for c in columns if c not in claimed and available(c)]
    return plan


def _resolve(spec: MetricSpec, column: str) -> MetricColumn | None:
    if spec.column is not None:
        if column != spec.column:
            return None
        return MetricColumn(
            column, spec.name or column, {}, spec.unit, spec.unit_column
        )
    assert spec.pattern is not None
    match = re.fullmatch(spec.pattern, column)
    if match is None:
        return None
    groups = {k: v for k, v in match.groupdict().items() if v is not None}
    metric = groups.pop("metric")
    unit_column = spec.unit_column.format(**groups) if spec.unit_column else None
    return MetricColumn(column, metric, groups, spec.unit, unit_column)
```

Add to `lb_common/api.py` (keep `__all__` sorted):

```python
from lb_common.models.datasets import (
    MANIFEST_FILENAME,
    DatasetDescriptor,
    DatasetManifest,
    MetricColumn,
    MetricSpec,
    ValueColumn,
    WidePlan,
    plan_wide,
    read_manifest,
    write_manifest,
)
```

and the names `"MANIFEST_FILENAME", "DatasetDescriptor", "DatasetManifest", "MetricColumn", "MetricSpec", "ValueColumn", "WidePlan", "plan_wide", "read_manifest", "write_manifest"` in `__all__`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest -q -p no:cacheprovider tests/unit/lb_common/test_datasets.py`
Expected: PASS (10 tests).

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check lb_common tests/unit/lb_common && uv run ruff format lb_common tests/unit/lb_common
git add lb_common tests/unit/lb_common/test_datasets.py
git commit -m "Add the dataset manifest model to lb_common

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Real-output fixtures, plugin hook and contract test

**Files:**
- Create: `tests/fixtures/plugin_outputs/` (generated, see Step 1)
- Create: `lb_plugins/datasets.py`
- Modify: `lb_plugins/interface.py` (new `WorkloadPlugin.describe_datasets`)
- Modify: `.pre-commit-config.yaml` (keep fixtures byte-faithful)
- Test: `tests/unit/lb_plugins/test_dataset_declarations.py`

**Interfaces:**
- Consumes: `DatasetDescriptor`, `MetricSpec`, `plan_wide` from `lb_common.api` (Task 1).
- Produces: `WorkloadPlugin.describe_datasets(self, output_dir: Path, test_name: str) -> list[DatasetDescriptor]`; in `lb_plugins/datasets.py`: `STANDARD_EXCLUDES: tuple[str, ...]` and `plugin_csv_dataset(test_name: str, *, metrics: Sequence[MetricSpec], keys: Sequence[str] = (), exclude: Sequence[str] = (), suffix: str = "plugin") -> DatasetDescriptor`; test module constant `DECLARED: list[str]` that later tasks extend.

- [ ] **Step 1: Build fixtures from the real Multipass outputs**

The outputs of the 2026-10-08 verification runs are under the session scratchpad. Copy and trim them (drop repetitions ≥ 2, logs and per-rep `result.json`; empty `metrics` and `stdout` in `*_results.json` — yabs keeps `stdout` because its export parses it):

```bash
uv run python - <<'EOF'
import json
import shutil
from pathlib import Path

SRC = Path("/tmp/claude-1000/-home-michele-Documenti-linux-benchmark-lib/"
           "13434f97-5493-4b26-8c2d-c2d4208acfd3/scratchpad/runs")
DST = Path("tests/fixtures/plugin_outputs")
WORKLOADS = ["baseline", "dd", "fio", "hpl", "stream", "stress_ng", "sysbench",
             "unixbench", "yabs", "geekbench", "pts_ramspeed", "pts_compress_7zip",
             "dfaas", "peva_faas"]
for workload in WORKLOADS:
    src = next(SRC.glob(f"{workload}/results/*/*/{workload}"))
    dst = DST / workload
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(
        "rep[2-9]*", "logs", "k6", "result.json"))
    results_file = dst / f"{workload}_results.json"
    entries = json.loads(results_file.read_text())
    for entry in entries:
        entry["metrics"] = {}
        gen = entry.get("generator_result") or {}
        if workload != "yabs" and isinstance(gen.get("stdout"), str):
            gen["stdout"] = ""
    results_file.write_text(json.dumps(entries, indent=1) + "\n")
host_dir = DST / "_host"
host_dir.mkdir(parents=True, exist_ok=True)
shutil.copy(next(SRC.glob("stress_ng/results/*/*/system_info.csv")),
            host_dir / "system_info.csv")
journal = json.loads(next(SRC.glob("stress_ng/results/*/run_journal.json")).read_text())
meta = {k: journal["metadata"][k] for k in ("created_at", "config_hash", "repetitions")}
run_dir = DST / "_run"
run_dir.mkdir(exist_ok=True)
(run_dir / "run_journal.json").write_text(
    json.dumps({"run_id": journal["run_id"], "metadata": meta}, indent=1) + "\n")
EOF
du -sh tests/fixtures/plugin_outputs; find tests/fixtures/plugin_outputs -size +400k
```

Expected: the `find` prints nothing (every file is under the 500 KB `check-added-large-files` limit).

- [ ] **Step 2: Keep the fixtures out of the whitespace hooks**

In `.pre-commit-config.yaml`, extend the excludes of `end-of-file-fixer`, `trailing-whitespace` and `mixed-line-ending` so captured outputs stay byte-for-byte real:

```yaml
      - id: end-of-file-fixer
        exclude: (\.(png|jpg|jpeg|gif|ico|svg)$|^tests/fixtures/plugin_outputs/)
      - id: trailing-whitespace
        exclude: (\.(png|jpg|jpeg|gif|ico|svg|md)$|^tests/fixtures/plugin_outputs/)
      - id: mixed-line-ending
        exclude: ^tests/fixtures/plugin_outputs/
```

- [ ] **Step 3: Write the failing contract test**

```python
# tests/unit/lb_plugins/test_dataset_declarations.py
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
    assert exported <= declared_files, (
        f"undeclared: {sorted(exported - declared_files)}"
    )
```

- [ ] **Step 4: Run it to verify it fails**

Run: `uv run pytest -q -p no:cacheprovider tests/unit/lb_plugins/test_dataset_declarations.py`
Expected: FAIL with `AttributeError: ... has no attribute 'describe_datasets'`.

- [ ] **Step 5: Add the helper and the default hook**

```python
# lb_plugins/datasets.py
"""Helpers for plugins declaring their exported datasets."""

from __future__ import annotations

from collections.abc import Sequence

from lb_common.api import DatasetDescriptor, MetricSpec

# Columns every plugin CSV carries that are not measurements: identity,
# repetition status (it lives in the repetitions table) and raw output.
STANDARD_EXCLUDES: tuple[str, ...] = (
    "run_id",
    "workload",
    "success",
    "duration_seconds",
    "returncode",
    "max_retries",
    "tags",
    "generator_stdout",
    "generator_stderr",
    "generator_command",
    "generator_returncode",
    "generator_max_retries",
    "generator_tags",
)


def plugin_csv_dataset(
    test_name: str,
    *,
    metrics: Sequence[MetricSpec],
    keys: Sequence[str] = (),
    exclude: Sequence[str] = (),
    suffix: str = "plugin",
) -> DatasetDescriptor:
    """Describe the wide ``<test_name>_<suffix>.csv`` a plugin exports."""
    return DatasetDescriptor(
        name=f"{test_name}_{suffix}",
        path=f"{test_name}_{suffix}.csv",
        shape="wide",
        keys=list(keys),
        metrics=list(metrics),
        exclude=[*STANDARD_EXCLUDES, *exclude],
    )
```

In `lb_plugins/interface.py`, import `from lb_common.api import DatasetDescriptor, MetricSpec` and `from lb_plugins.datasets import plugin_csv_dataset`, then add to `WorkloadPlugin` right after `export_results_to_csv`:

```python
    def describe_datasets(
        self, output_dir: Path, test_name: str
    ) -> list[DatasetDescriptor]:
        """Declare the datasets this plugin exported into ``output_dir``.

        The runner writes them into ``datasets.json`` for ``lb_analytics``.
        The default matches the default ``export_results_to_csv``: every
        ``generator_*`` field is a metric. Plugins with string fields or their
        own export override this.
        """
        if not (output_dir / f"{test_name}_plugin.csv").exists():
            return []
        return [
            plugin_csv_dataset(
                test_name,
                metrics=[MetricSpec(pattern=r"^generator_(?P<metric>.+)$")],
            )
        ]
```

- [ ] **Step 6: Run the contract test to verify it passes**

Run: `uv run pytest -q -p no:cacheprovider tests/unit/lb_plugins/test_dataset_declarations.py`
Expected: PASS (1 test: `sysbench`).

- [ ] **Step 7: Commit**

```bash
uv run pre-commit run --files $(git ls-files -o --exclude-standard tests/fixtures/plugin_outputs) .pre-commit-config.yaml lb_plugins/datasets.py lb_plugins/interface.py tests/unit/lb_plugins/test_dataset_declarations.py
git add tests/fixtures/plugin_outputs .pre-commit-config.yaml lb_plugins/datasets.py lb_plugins/interface.py tests/unit/lb_plugins/test_dataset_declarations.py
git commit -m "Let plugins declare their datasets; add real-output fixtures

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Declarations for the wide plugins

**Files:**
- Modify: `lb_plugins/plugins/baseline/plugin.py`, `stress_ng/plugin.py`, `sysbench/plugin.py`, `unixbench/plugin.py`, `fio/plugin.py`, `dd/plugin.py`, `hpl/plugin.py`, `stream/plugin.py` (one `describe_datasets` override each)
- Test: `tests/unit/lb_plugins/test_dataset_declarations.py` (extend `DECLARED`, add value checks)

**Interfaces:**
- Consumes: `plugin_csv_dataset` from `lb_plugins.datasets`; `MetricSpec` from `lb_common.api`.

- [ ] **Step 1: Extend the contract test and add hand-checked declarations**

```python
DECLARED: list[str] = [
    "sysbench",
    "baseline",
    "stress_ng",
    "unixbench",
    "fio",
    "dd",
    "hpl",
    "stream",
]


def _metrics(tmp_path: Path, workload: str) -> dict[tuple, str | None]:
    """Map (metric, sorted dims) -> unit for the plugin's main CSV."""
    work = _export(tmp_path, workload)
    [d, *_] = create_registry().get(workload).describe_datasets(work, workload)
    frame = pd.read_csv(work / d.path)
    return {
        (m.metric, tuple(sorted(m.dims.items()))): m.unit
        for m in plan_wide(d, list(frame.columns)).metrics
    }


def test_stress_ng_declares_per_stressor_metrics(tmp_path: Path) -> None:
    metrics = _metrics(tmp_path, "stress_ng")
    assert metrics[("bogo_ops", (("stressor", "cpu"),))] == "ops"
    assert metrics[("bogo_ops_per_s_real", (("stressor", "vm"),))] == "ops/s"


def test_unixbench_reads_units_from_its_unit_columns(tmp_path: Path) -> None:
    work = _export(tmp_path, "unixbench")
    [d] = create_registry().get("unixbench").describe_datasets(work, "unixbench")
    plan = plan_wide(d, list(pd.read_csv(work / d.path).columns))
    result = next(m for m in plan.metrics if m.metric == "result")
    assert result.unit_column == f"generator_{result.dims['test']}_unit"
    assert any(m.metric == "index_score" for m in plan.metrics)


def test_fio_splits_direction_into_a_dimension(tmp_path: Path) -> None:
    metrics = _metrics(tmp_path, "fio")
    assert metrics[("iops", (("direction", "read"),))] == "IOPS"
    assert metrics[("lat_ms", (("direction", "write"),))] == "ms"


def test_stream_keeps_seconds_and_drops_millisecond_copies(tmp_path: Path) -> None:
    metrics = _metrics(tmp_path, "stream")
    assert metrics[("best_rate_mb_s", (("kernel", "triad"),))] == "MB/s"
    assert ("avg_time_ms", (("kernel", "copy"),)) not in metrics
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest -q -p no:cacheprovider tests/unit/lb_plugins/test_dataset_declarations.py`
Expected: FAIL — `baseline` (string `generator_status` declared as a metric), `stress_ng`, `fio`, `dd`, `hpl`, `stream` (undeclared numeric columns or wrong metric names), and the four value tests.

- [ ] **Step 3: Add the overrides**

Each override is a method on the plugin class; add `from lb_common.api import DatasetDescriptor, MetricSpec` and `from lb_plugins.datasets import plugin_csv_dataset` to each module.

`baseline`:

```python
def describe_datasets(
    self, output_dir: Path, test_name: str
) -> list[DatasetDescriptor]:
    return [
        plugin_csv_dataset(
            test_name,
            metrics=[
                MetricSpec(
                    column="generator_target_duration", name="target_duration", unit="s"
                ),
                MetricSpec(
                    column="generator_actual_duration", name="actual_duration", unit="s"
                ),
            ],
        )
    ]
```

`stress_ng`:

```python
_STRESSOR = r"^generator_(?P<stressor>.+?)_"

    def describe_datasets(self, output_dir: Path, test_name: str) -> list[DatasetDescriptor]:
        return [
            plugin_csv_dataset(
                test_name,
                metrics=[
                    MetricSpec(pattern=_STRESSOR + r"(?P<metric>bogo_ops)$", unit="ops"),
                    MetricSpec(pattern=_STRESSOR + r"(?P<metric>real_time_s|usr_time_s|sys_time_s)$", unit="s"),
                    MetricSpec(pattern=_STRESSOR + r"(?P<metric>bogo_ops_per_s_real|bogo_ops_per_s_cpu)$", unit="ops/s"),
                    MetricSpec(pattern=_STRESSOR + r"(?P<metric>cpu_used_per_instance_pct)$", unit="%"),
                    MetricSpec(pattern=_STRESSOR + r"(?P<metric>rss_max_kb)$", unit="KB"),
                ],
            )
        ]
```

`sysbench`:

```python
def describe_datasets(
    self, output_dir: Path, test_name: str
) -> list[DatasetDescriptor]:
    return [
        plugin_csv_dataset(
            test_name,
            metrics=[
                MetricSpec(
                    column="generator_events_per_second",
                    name="events_per_second",
                    unit="events/s",
                ),
                MetricSpec(
                    column="generator_total_time_seconds",
                    name="total_time_seconds",
                    unit="s",
                ),
                MetricSpec(
                    column="generator_total_events", name="total_events", unit="events"
                ),
                MetricSpec(
                    pattern=r"^generator_(?P<metric>latency_(?:min|avg|max|p95|sum)_ms)$",
                    unit="ms",
                ),
            ],
        )
    ]
```

`unixbench`:

```python
def describe_datasets(
    self, output_dir: Path, test_name: str
) -> list[DatasetDescriptor]:
    return [
        plugin_csv_dataset(
            test_name,
            metrics=[
                MetricSpec(
                    pattern=r"^generator_(?P<test>.+)_(?P<metric>result)$",
                    unit_column="generator_{test}_unit",
                ),
                MetricSpec(
                    pattern=r"^generator_(?P<test>.+)_(?P<metric>index)$", unit="index"
                ),
                MetricSpec(
                    column="generator_index_score", name="index_score", unit="index"
                ),
            ],
        )
    ]
```

`fio`:

```python
_DIRECTION = r"^(?P<direction>read|write)_"

    def describe_datasets(self, output_dir: Path, test_name: str) -> list[DatasetDescriptor]:
        return [
            plugin_csv_dataset(
                test_name,
                metrics=[
                    MetricSpec(pattern=_DIRECTION + r"(?P<metric>iops)$", unit="IOPS"),
                    MetricSpec(pattern=_DIRECTION + r"(?P<metric>bw_mb)$", unit="MB/s"),
                    MetricSpec(pattern=_DIRECTION + r"(?P<metric>lat_ms)$", unit="ms"),
                ],
            )
        ]
```

`dd` (`dd_rate` duplicates `dd_bytes_per_sec` in a varying unit, so it is excluded):

```python
def describe_datasets(
    self, output_dir: Path, test_name: str
) -> list[DatasetDescriptor]:
    return [
        plugin_csv_dataset(
            test_name,
            metrics=[
                MetricSpec(column="dd_bytes", unit="B"),
                MetricSpec(column="dd_seconds", unit="s"),
                MetricSpec(column="dd_bytes_per_sec", unit="B/s"),
            ],
            exclude=["dd_rate"],
        )
    ]
```

`hpl`:

```python
def describe_datasets(
    self, output_dir: Path, test_name: str
) -> list[DatasetDescriptor]:
    return [
        plugin_csv_dataset(
            test_name,
            keys=["n", "nb", "p", "q"],
            metrics=[
                MetricSpec(column="time_seconds", unit="s"),
                MetricSpec(column="gflops", unit="GFLOPS"),
                MetricSpec(column="residual"),
            ],
            exclude=["residual_passed"],
        )
    ]
```

`stream`:

```python
_KERNEL = r"^(?P<kernel>copy|scale|add|triad)_"

    def describe_datasets(self, output_dir: Path, test_name: str) -> list[DatasetDescriptor]:
        return [
            plugin_csv_dataset(
                test_name,
                keys=["compiler", "stream_array_size", "ntimes", "threads"],
                metrics=[
                    MetricSpec(pattern=_KERNEL + r"(?P<metric>best_rate_mb_s)$", unit="MB/s"),
                    MetricSpec(pattern=_KERNEL + r"(?P<metric>avg_time_s|min_time_s|max_time_s)$", unit="s"),
                ],
                exclude=[r"(copy|scale|add|triad)_(avg|min|max)_time_ms", "validated"],
            )
        ]
```

Module-level regex constants (`_STRESSOR`, `_DIRECTION`, `_KERNEL`) go above the plugin class. Let `ruff format` wrap the long lines.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest -q -p no:cacheprovider tests/unit/lb_plugins/test_dataset_declarations.py`
Expected: PASS (8 parametrized + 4 value tests).

- [ ] **Step 5: Commit**

```bash
uv run ruff check lb_plugins tests/unit/lb_plugins && uv run ruff format lb_plugins tests/unit/lb_plugins
git add lb_plugins/plugins tests/unit/lb_plugins/test_dataset_declarations.py
git commit -m "Declare the datasets of the wide-CSV plugins

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Declarations for yabs, Geekbench and PTS

**Files:**
- Modify: `lb_plugins/plugins/yabs/plugin.py`, `geekbench/plugin.py`, `phoronix_test_suite/plugin.py`
- Test: `tests/unit/lb_plugins/test_dataset_declarations.py`

**Interfaces:**
- Consumes: `plugin_csv_dataset`, `DatasetDescriptor`, `MetricSpec`, `ValueColumn`.

- [ ] **Step 1: Extend the test**

```python
DECLARED: list[str] = [
    "sysbench",
    "baseline",
    "stress_ng",
    "unixbench",
    "fio",
    "dd",
    "hpl",
    "stream",
    "yabs",
    "geekbench",
    "pts_ramspeed",
    "pts_compress_7zip",
]


def test_yabs_declares_iperf_as_long(tmp_path: Path) -> None:
    work = _export(tmp_path, "yabs")
    names = {
        d.name: d for d in create_registry().get("yabs").describe_datasets(work, "yabs")
    }
    iperf = names["yabs_iperf"]
    assert iperf.shape == "long"
    assert {v.column: v.unit for v in iperf.value_columns} == {
        "send_mbits": "Mbit/s",
        "recv_mbits": "Mbit/s",
        "latency_ms": "ms",
    }


def test_pts_reads_values_and_units_from_composite_rows(tmp_path: Path) -> None:
    work = _export(tmp_path, "pts_compress_7zip")
    descriptors = (
        create_registry()
        .get("pts_compress_7zip")
        .describe_datasets(work, "pts_compress_7zip")
    )
    by_name = {d.name: d for d in descriptors}
    assert by_name["pts_compress_7zip_pts"].target_table == "ignore"
    values = by_name["pts_compress_7zip_pts_results"]
    assert (values.metric_column, values.value_column, values.unit_column) == (
        "test",
        "value",
        "scale",
    )
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest -q -p no:cacheprovider tests/unit/lb_plugins/test_dataset_declarations.py`
Expected: FAIL for `yabs`, `geekbench`, `pts_*` and the two new tests.

- [ ] **Step 3: Add the overrides**

`yabs` (host facts duplicated from `system_info` are excluded):

```python
_BLOCK = r"^fio_(?P<block_size>[^_]+)_"

    def describe_datasets(self, output_dir: Path, test_name: str) -> list[DatasetDescriptor]:
        datasets = [
            plugin_csv_dataset(
                test_name,
                metrics=[
                    MetricSpec(pattern=_BLOCK + r"(?P<metric>speed_(?:r|w|rw))$", unit="KB/s"),
                    MetricSpec(pattern=_BLOCK + r"(?P<metric>iops_(?:r|w|rw))$", unit="IOPS"),
                ],
                exclude=["cpu_cores", "ram_kib", "swap_kib", "disk_kb", "cpu_aes"],
            )
        ]
        if (output_dir / f"{test_name}_iperf.csv").exists():
            datasets.append(
                DatasetDescriptor(
                    name=f"{test_name}_iperf",
                    path=f"{test_name}_iperf.csv",
                    shape="long",
                    keys=["mode", "provider", "location"],
                    value_columns=[
                        ValueColumn(column="send_mbits", unit="Mbit/s"),
                        ValueColumn(column="recv_mbits", unit="Mbit/s"),
                        ValueColumn(column="latency_ms", unit="ms"),
                    ],
                )
            )
        return datasets
```

`geekbench`:

```python
def describe_datasets(
    self, output_dir: Path, test_name: str
) -> list[DatasetDescriptor]:
    datasets = [
        plugin_csv_dataset(
            test_name,
            metrics=[
                MetricSpec(column="single_core_score", unit="points"),
                MetricSpec(column="multi_core_score", unit="points"),
            ],
            exclude=["export_json_supported"],
        )
    ]
    if (output_dir / f"{test_name}_subtests.csv").exists():
        datasets.append(
            DatasetDescriptor(
                name=f"{test_name}_subtests",
                path=f"{test_name}_subtests.csv",
                shape="long",
                keys=["subtest"],
                value_columns=[ValueColumn(column="score", unit="points")],
            )
        )
    return datasets
```

`PhoronixTestSuiteWorkloadPlugin` (the `_pts.csv` summary holds no measurement: declared and ignored):

```python
def describe_datasets(
    self, output_dir: Path, test_name: str
) -> list[DatasetDescriptor]:
    datasets = [
        DatasetDescriptor(
            name=f"{test_name}_pts",
            path=f"{test_name}_pts.csv",
            shape="wide",
            table="ignore",
        )
    ]
    if (output_dir / f"{test_name}_pts_results.csv").exists():
        datasets.append(
            DatasetDescriptor(
                name=f"{test_name}_pts_results",
                path=f"{test_name}_pts_results.csv",
                shape="long",
                # app_version parses as a number for some profiles (7zip: 26.01).
                keys=["description", "arguments", "system", "app_version"],
                metric_column="test",
                value_column="value",
                unit_column="scale",
                exclude=["samples"],
            )
        )
    return datasets
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest -q -p no:cacheprovider tests/unit/lb_plugins/test_dataset_declarations.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff check lb_plugins && uv run ruff format lb_plugins tests/unit/lb_plugins
git add lb_plugins/plugins tests/unit/lb_plugins/test_dataset_declarations.py
git commit -m "Declare the datasets of yabs, Geekbench and PTS

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: dfaas and peva_faas: `results_long.csv` and declarations

**Files:**
- Create: `lb_plugins/plugins/_faas_shared/datasets.py`
- Modify: `lb_plugins/plugins/dfaas/plugin.py`, `lb_plugins/plugins/peva_faas/plugin.py` (write `results_long.csv` in `export_results_to_csv`; add `describe_datasets`)
- Test: `tests/unit/lb_plugins/test_faas_datasets.py`, `tests/unit/lb_plugins/test_dataset_declarations.py`

**Interfaces:**
- Consumes: `config_id` from `lb_plugins.plugins._faas_shared.config_enumerator`.
- Produces: `long_rows(results: list[dict[str, Any]], prefix: str) -> list[dict[str, Any]]` (prefix is `"dfaas"` or `"peva_faas"`, the key prefix of `generator_result`), `write_results_long(path: Path, rows: list[dict[str, Any]]) -> None`, `faas_datasets(output_dir: Path) -> list[DatasetDescriptor]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/lb_plugins/test_faas_datasets.py
import pytest

from lb_plugins.plugins._faas_shared.config_enumerator import config_id
from lb_plugins.plugins._faas_shared.datasets import long_rows

pytestmark = pytest.mark.unit_plugins


def test_long_rows_split_functions_and_node_metrics() -> None:
    row = {
        "function_env": "env",
        "rate_function_env": 5,
        "success_rate_function_env": "1.000",
        "cpu_usage_function_env": "0.409",
        "ram_usage_function_env": "6875136.0",
        "power_usage_function_env": "nan",
        "replica_env": 1,
        "overloaded_function_env": 0,
        "medium_latency_function_env": "3.426",
        "function_figlet": "",
        "rate_function_figlet": "",
        "cpu_usage_node": "13.4",
        "rest_seconds": 0,
    }
    results = [
        {
            "repetition": 1,
            "generator_result": {
                "dfaas_functions": ["env", "figlet"],
                "dfaas_results": [row],
            },
        }
    ]
    rows = long_rows(results, "dfaas")
    env = {r["metric"]: r for r in rows if r["function"] == "env"}
    assert env["cpu_usage"]["value"] == "0.409"
    assert env["cpu_usage"]["unit"] == "%"
    assert env["medium_latency"]["unit"] == "ms"
    assert env["cpu_usage"]["config_id"] == config_id([("env", 5)])
    assert env["cpu_usage"]["rate"] == 5
    assert not [r for r in rows if r["function"] == "figlet"]
    node = {r["metric"]: r for r in rows if r["function"] == ""}
    assert node["cpu_usage_node"]["unit"] == "%"
    assert node["rest_seconds"]["rate"] == ""
    assert {r["repetition"] for r in rows} == {1}
```

Extend `DECLARED` with `"dfaas", "peva_faas"` and add:

```python
def test_faas_metrics_files_carry_config_and_iteration(tmp_path: Path) -> None:
    work = _export(tmp_path, "dfaas")
    descriptors = create_registry().get("dfaas").describe_datasets(work, "dfaas")
    metrics_files = [d for d in descriptors if d.path.startswith("metrics/")]
    assert metrics_files
    assert {"config_id", "iteration", "repetition"} <= set(metrics_files[0].fixed)
    ignored = {d.path for d in descriptors if d.target_table == "ignore"}
    assert {"results.csv", "skipped.csv", "index.csv"} <= ignored
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest -q -p no:cacheprovider tests/unit/lb_plugins/test_faas_datasets.py tests/unit/lb_plugins/test_dataset_declarations.py`
Expected: FAIL with `ModuleNotFoundError: ... _faas_shared.datasets`.

- [ ] **Step 3: Implement the shared module**

```python
# lb_plugins/plugins/_faas_shared/datasets.py
"""Tidy export and dataset declarations shared by dfaas and peva_faas.

``results.csv`` keeps the legacy layout (one row per configuration, columns per
function). ``results_long.csv`` restates it as one row per configuration x
function x metric, which is what ``lb_analytics`` loads.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

from lb_common.api import DatasetDescriptor, MetricSpec
from lb_plugins.plugins._faas_shared.config_enumerator import config_id

# Units follow queries.yml and the k6 summary: CPU is 100 * cores, memory in
# bytes, Scaphandre power in microwatts, k6 latency in milliseconds.
_FUNCTION_METRICS = {
    "success_rate": ("success_rate_function_{}", "ratio"),
    "cpu_usage": ("cpu_usage_function_{}", "%"),
    "ram_usage": ("ram_usage_function_{}", "B"),
    "power_usage": ("power_usage_function_{}", "uW"),
    "replicas": ("replica_{}", "count"),
    "overloaded": ("overloaded_function_{}", "flag"),
    "medium_latency": ("medium_latency_function_{}", "ms"),
}
_NODE_METRICS = {
    "cpu_usage_idle_node": "%",
    "cpu_usage_node": "%",
    "ram_usage_idle_node": "B",
    "ram_usage_node": "B",
    "ram_usage_idle_node_percentage": "%",
    "ram_usage_node_percentage": "%",
    "power_usage_idle_node": "uW",
    "power_usage_node": "uW",
    "rest_seconds": "s",
    "overloaded_node": "flag",
}
_LONG_COLUMNS = [
    "repetition",
    "config_id",
    "function",
    "rate",
    "metric",
    "value",
    "unit",
]
_METRICS_FILE = re.compile(
    r"^metrics-(?P<config_id>[0-9a-f]+)-iter(?P<iteration>\d+)-rep(?P<rep>\d+)\.csv$"
)


def long_rows(results: list[dict[str, Any]], prefix: str) -> list[dict[str, Any]]:
    """Restate the legacy results rows as configuration x function x metric."""
    rows: list[dict[str, Any]] = []
    for entry in results:
        gen = entry.get("generator_result") or {}
        functions = list(gen.get(f"{prefix}_functions") or [])
        for result in gen.get(f"{prefix}_results") or []:
            active = [f for f in functions if result.get(f"function_{f}")]
            pairs = [(f, int(result[f"rate_function_{f}"])) for f in active]
            base = {
                "repetition": entry.get("repetition"),
                "config_id": config_id(pairs),
            }
            for function, rate in pairs:
                for metric, (column, unit) in _FUNCTION_METRICS.items():
                    rows.append(
                        {
                            **base,
                            "function": function,
                            "rate": rate,
                            "metric": metric,
                            "value": result.get(column.format(function), ""),
                            "unit": unit,
                        }
                    )
            for metric, unit in _NODE_METRICS.items():
                if metric in result:
                    rows.append(
                        {
                            **base,
                            "function": "",
                            "rate": "",
                            "metric": metric,
                            "value": result[metric],
                            "unit": unit,
                        }
                    )
    return rows


def write_results_long(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_LONG_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def faas_datasets(output_dir: Path) -> list[DatasetDescriptor]:
    """Declare what a FaaS export wrote into ``output_dir``."""
    datasets = [
        DatasetDescriptor(
            name="results_legacy", path="results.csv", shape="wide", table="ignore"
        ),
        DatasetDescriptor(
            name="skipped", path="skipped.csv", shape="wide", table="ignore"
        ),
        DatasetDescriptor(name="index", path="index.csv", shape="wide", table="ignore"),
        DatasetDescriptor(
            name="results_long",
            path="results_long.csv",
            shape="long",
            keys=["config_id", "function", "rate"],
            metric_column="metric",
            value_column="value",
            unit_column="unit",
        ),
    ]
    for path in sorted((output_dir / "metrics").glob("metrics-*.csv")):
        match = _METRICS_FILE.match(path.name)
        if match is None:
            continue
        datasets.append(
            DatasetDescriptor(
                name=path.stem,
                path=f"metrics/{path.name}",
                shape="wide",
                fixed={
                    "repetition": int(match["rep"]),
                    "config_id": match["config_id"],
                    "iteration": int(match["iteration"]),
                },
                metrics=[
                    MetricSpec(
                        pattern=r"^(?P<metric>cpu_usage)_function_(?P<function>.+)$",
                        unit="%",
                    ),
                    MetricSpec(
                        pattern=r"^(?P<metric>ram_usage)_function_(?P<function>.+)$",
                        unit="B",
                    ),
                    MetricSpec(
                        pattern=r"^(?P<metric>power_usage)_function_(?P<function>.+)$",
                        unit="uW",
                    ),
                    MetricSpec(column="cpu_usage_node", unit="%"),
                    MetricSpec(column="ram_usage_node", unit="B"),
                    MetricSpec(column="ram_usage_node_pct", unit="%"),
                    MetricSpec(column="power_usage_node", unit="uW"),
                ],
            )
        )
    return datasets
```

- [ ] **Step 4: Wire both plugins**

In `lb_plugins/plugins/dfaas/plugin.py`, inside `export_results_to_csv`, right after `index.csv` is written:

```python
        long_path = output_dir / "results_long.csv"
        write_results_long(long_path, long_rows(results, "dfaas"))
        paths.append(long_path)
```

and add to `DfaasPlugin`:

```python
def describe_datasets(
    self, output_dir: Path, test_name: str
) -> list[DatasetDescriptor]:
    return faas_datasets(output_dir)
```

Do the same in `lb_plugins/plugins/peva_faas/plugin.py` with prefix `"peva_faas"`. Imports in both: `from lb_common.api import DatasetDescriptor` and `from lb_plugins.plugins._faas_shared.datasets import faas_datasets, long_rows, write_results_long`.

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest -q -p no:cacheprovider tests/unit/lb_plugins/test_faas_datasets.py tests/unit/lb_plugins/test_dataset_declarations.py tests/unit/lb_plugins/dfaas tests/unit/lb_plugins/peva_faas`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
uv run ruff check lb_plugins && uv run ruff format lb_plugins tests/unit/lb_plugins
git add lb_plugins/plugins tests/unit/lb_plugins
git commit -m "Export FaaS results in long form and declare the FaaS datasets

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: The runner writes the manifests

**Files:**
- Create: `lb_runner/services/dataset_manifest.py`
- Modify: `lb_runner/services/results.py` (`export_plugin_results`)
- Modify: `lb_runner/services/storage.py` (`write_system_info_artifacts`)
- Modify: `lb_runner/api.py` (export `write_workload_manifest`, `write_host_manifest`)
- Modify: `lb_controller/ansible/playbooks/collect.yml` (fetch the host manifest)
- Test: `tests/unit/lb_runner/test_dataset_manifest.py`

**Interfaces:**
- Consumes: `DatasetDescriptor`, `DatasetManifest`, `write_manifest` (Task 1); `WorkloadPlugin.describe_datasets` (Task 2).
- Produces: `collector_datasets(workload_dir: Path, test_name: str) -> list[DatasetDescriptor]`, `write_workload_manifest(plugin: WorkloadPlugin | None, workload_dir: Path, test_name: str) -> Path`, `write_host_manifest(host_dir: Path) -> Path`, `SYSTEM_INFO_DATASET: DatasetDescriptor`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/lb_runner/test_dataset_manifest.py
import shutil
from pathlib import Path

import pytest

from lb_common.api import read_manifest
from lb_plugins.api import create_registry
from lb_runner.api import write_host_manifest, write_workload_manifest

pytestmark = pytest.mark.unit_runner

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "plugin_outputs"


def test_workload_manifest_merges_plugin_and_collector_datasets(tmp_path: Path) -> None:
    work = tmp_path / "stress_ng"
    shutil.copytree(FIXTURES / "stress_ng", work)
    plugin = create_registry().get("stress_ng")
    write_workload_manifest(plugin, work, "stress_ng")
    manifest = read_manifest(work)
    assert (manifest.workload, manifest.plugin) == ("stress_ng", "stress_ng")
    assert manifest.repetitions == "stress_ng_results.json"
    by_name = {d.name: d for d in manifest.datasets}
    assert "stress_ng_plugin" in by_name
    psutil = by_name["stress_ng_rep1_PSUtilCollector"]
    assert psutil.shape == "timeseries"
    assert psutil.fixed == {"repetition": 1, "collector": "PSUtilCollector"}
    assert psutil.path == "rep1/stress_ng_rep1_PSUtilCollector.csv"


def test_workload_manifest_without_plugin_keeps_collectors(tmp_path: Path) -> None:
    work = tmp_path / "fio"
    shutil.copytree(FIXTURES / "fio", work)
    write_workload_manifest(None, work, "fio")
    manifest = read_manifest(work)
    assert manifest.plugin is None
    assert all(d.shape == "timeseries" for d in manifest.datasets)


def test_host_manifest_declares_system_info(tmp_path: Path) -> None:
    write_host_manifest(tmp_path)
    [dataset] = read_manifest(tmp_path).datasets
    assert (dataset.path, dataset.target_table) == ("system_info.csv", "host_info")
```

Also add an assertion to the existing persistence path: in a new test, call `export_plugin_results` and check the manifest exists:

```python
def test_export_plugin_results_writes_the_manifest(tmp_path: Path) -> None:
    import json

    from lb_runner.services.results import export_plugin_results

    work = tmp_path / "sysbench"
    shutil.copytree(FIXTURES / "sysbench", work)
    results = json.loads((work / "sysbench_results.json").read_text())
    export_plugin_results(
        create_registry().get("sysbench"), results, work, "sysbench", "r1"
    )
    assert (work / "datasets.json").exists()
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest -q -p no:cacheprovider tests/unit/lb_runner/test_dataset_manifest.py`
Expected: FAIL with `ImportError: cannot import name 'write_host_manifest' from 'lb_runner.api'`.

- [ ] **Step 3: Implement the writer**

```python
# lb_runner/services/dataset_manifest.py
"""Write the datasets.json manifests that lb_analytics loads."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from lb_common.api import DatasetDescriptor, DatasetManifest, write_manifest
from lb_plugins.api import WorkloadPlugin

logger = logging.getLogger(__name__)

# Collector files are named <test>_rep<N>_<Collector>.csv by collect_metrics().
_COLLECTOR_FILE = re.compile(r"^(?P<test>.+)_rep(?P<rep>\d+)_(?P<collector>.+)\.csv$")

SYSTEM_INFO_DATASET = DatasetDescriptor(
    name="system_info",
    path="system_info.csv",
    shape="long",
    table="host_info",
    keys=["category", "name"],
    value_column="value",
)


def collector_datasets(workload_dir: Path, test_name: str) -> list[DatasetDescriptor]:
    """One timeseries descriptor per collector CSV under ``rep*/``."""
    datasets = []
    for path in sorted(workload_dir.glob("rep*/*.csv")):
        match = _COLLECTOR_FILE.match(path.name)
        if match is None or match["test"] != test_name:
            continue
        datasets.append(
            DatasetDescriptor(
                name=path.stem,
                path=path.relative_to(workload_dir).as_posix(),
                shape="timeseries",
                time_column="timestamp",
                fixed={
                    "repetition": int(match["rep"]),
                    "collector": match["collector"],
                },
            )
        )
    return datasets


def write_workload_manifest(
    plugin: WorkloadPlugin | None, workload_dir: Path, test_name: str
) -> Path:
    """Write ``<workload_dir>/datasets.json``: plugin datasets plus collectors."""
    datasets: list[DatasetDescriptor] = []
    if plugin is not None:
        try:
            datasets.extend(plugin.describe_datasets(workload_dir, test_name))
        except Exception as exc:
            logger.warning("Plugin '%s' describe_datasets failed: %s", plugin.name, exc)
    datasets.extend(collector_datasets(workload_dir, test_name))
    manifest = DatasetManifest(
        workload=test_name,
        plugin=plugin.name if plugin is not None else None,
        repetitions=f"{test_name}_results.json",
        datasets=datasets,
    )
    return write_manifest(workload_dir, manifest)


def write_host_manifest(host_dir: Path) -> Path:
    """Write ``<host_dir>/datasets.json`` declaring ``system_info.csv``."""
    return write_manifest(host_dir, DatasetManifest(datasets=[SYSTEM_INFO_DATASET]))
```

In `lb_runner/services/results.py`, replace `export_plugin_results` so the manifest is written even without a plugin and never breaks the run:

```python
def export_plugin_results(
    plugin: WorkloadPlugin | None,
    merged_results: list[dict[str, Any]],
    target_root: Path,
    test_name: str,
    run_id: str,
) -> None:
    if plugin:
        try:
            exported = plugin.export_results_to_csv(
                results=merged_results,
                output_dir=target_root,
                run_id=run_id,
                test_name=test_name,
            )
            for path in exported:
                logger.info("Plugin exported CSV: %s", path)
        except Exception as exc:
            logger.warning(
                "Plugin '%s' export_results_to_csv failed: %s", plugin.name, exc
            )
    try:
        write_workload_manifest(plugin, target_root, test_name)
    except Exception as exc:
        logger.warning("Writing datasets.json for '%s' failed: %s", test_name, exc)
```

with `from lb_runner.services.dataset_manifest import write_workload_manifest`.

In `lb_runner/services/storage.py`, at the end of the `try` in `write_system_info_artifacts`:

```python
        write_outputs(collected, json_path, csv_path)
        write_host_manifest(output_root)
```

with `from lb_runner.services.dataset_manifest import write_host_manifest`.

In `lb_runner/api.py`, import and export `write_host_manifest` and `write_workload_manifest`.

In `lb_controller/ansible/playbooks/collect.yml`, task "Fetch system info artifacts (JSON + CSV)", add the manifest to the loop (workload manifests already travel inside the workload archive):

```yaml
      loop:
        - system_info.json
        - system_info.csv
        - datasets.json
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest -q -p no:cacheprovider tests/unit/lb_runner`
Expected: PASS (new tests plus the existing runner suite).

- [ ] **Step 5: Commit**

```bash
uv run ruff check lb_runner && uv run ruff format lb_runner tests/unit/lb_runner && uv run yamllint lb_controller/ansible/playbooks/collect.yml
git add lb_runner tests/unit/lb_runner/test_dataset_manifest.py lb_controller/ansible/playbooks/collect.yml
git commit -m "Write datasets.json manifests from the runner and collect them

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Dataset readers in `lb_analytics`

**Files:**
- Create: `lb_analytics/unify/__init__.py` (empty), `lb_analytics/unify/report.py`, `lb_analytics/unify/readers.py`
- Test: `tests/unit/lb_analytics/test_unify_readers.py`

**Interfaces:**
- Consumes: `DatasetDescriptor`, `plan_wide` from `lb_common.api`.
- Produces: `LoadReport` (dataclass with `files_read`, `errors`, `warnings`, `undeclared_files`, `not_loadable`, `failed_repetitions`, `ignored_columns`, `missing_values`; methods `error(source: str, message: str)`, `warn(source: str, message: str)`, `to_dict() -> dict`), `SourceContext(run_id: str, host: str, workload: str | None, plugin: str | None)`, `read_dataset(descriptor: DatasetDescriptor, path: Path, ctx: SourceContext, report: LoadReport) -> pd.DataFrame | None` returning a frame shaped for `descriptor.target_table`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/lb_analytics/test_unify_readers.py
from pathlib import Path

import pandas as pd
import pytest

from lb_analytics.unify.readers import SourceContext, read_dataset
from lb_analytics.unify.report import LoadReport
from lb_common.api import DatasetDescriptor, MetricSpec, ValueColumn

pytestmark = pytest.mark.unit_analytics

CTX = SourceContext(run_id="r1", host="h1", workload="w", plugin="p")


def _csv(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "data.csv"
    path.write_text(text)
    return path


def test_wide_turns_columns_into_metric_rows_with_dims(tmp_path: Path) -> None:
    d = DatasetDescriptor(
        name="s",
        path="data.csv",
        shape="wide",
        keys=["repetition"],
        metrics=[
            MetricSpec(pattern=r"^g_(?P<stressor>[a-z]+)_(?P<metric>ops)$", unit="ops")
        ],
    )
    path = _csv(
        tmp_path, "repetition,g_cpu_ops,g_vm_ops,run_id\n1,10,20,r1\n2,11,,r1\n"
    )
    report = LoadReport()
    frame = read_dataset(d, path, CTX, report)
    assert frame is not None
    assert sorted(frame["dim_stressor"]) == ["cpu", "cpu", "vm"]
    assert set(frame["unit"]) == {"ops"}
    row = frame[(frame.repetition == 2) & (frame.dim_stressor == "cpu")].iloc[0]
    assert (row["metric"], row["value"], row["dataset"]) == ("ops", 11.0, "s")
    assert report.missing_values == {"data.csv": 1}
    assert report.ignored_columns == {"data.csv": ["run_id"]}


def test_wide_rejects_a_non_numeric_metric_without_partial_rows(tmp_path: Path) -> None:
    d = DatasetDescriptor(
        name="s",
        path="data.csv",
        shape="wide",
        metrics=[MetricSpec(column="x", unit="s")],
    )
    report = LoadReport()
    assert (
        read_dataset(d, _csv(tmp_path, "repetition,x\n1,1.5\n2,fast\n"), CTX, report)
        is None
    )
    [error] = report.errors
    assert "x" in error["message"] and "1 non-numeric" in error["message"]


def test_wide_unit_column_is_read_per_row(tmp_path: Path) -> None:
    d = DatasetDescriptor(
        name="u",
        path="data.csv",
        shape="wide",
        metrics=[
            MetricSpec(
                pattern=r"^g_(?P<test>.+)_(?P<metric>result)$",
                unit_column="g_{test}_unit",
            )
        ],
    )
    frame = read_dataset(
        d,
        _csv(tmp_path, "repetition,g_dhry_result,g_dhry_unit\n1,7.5,lps\n"),
        CTX,
        LoadReport(),
    )
    assert frame is not None and frame.iloc[0]["unit"] == "lps"


def test_long_value_columns(tmp_path: Path) -> None:
    d = DatasetDescriptor(
        name="iperf",
        path="data.csv",
        shape="long",
        keys=["provider"],
        value_columns=[
            ValueColumn(column="send", unit="Mbit/s"),
            ValueColumn(column="lat", unit="ms"),
        ],
    )
    frame = read_dataset(
        d,
        _csv(tmp_path, "repetition,provider,send,lat\n1,A,900,30\n"),
        CTX,
        LoadReport(),
    )
    assert frame is not None
    assert set(zip(frame.metric, frame.unit, frame.value)) == {
        ("send", "Mbit/s", 900.0),
        ("lat", "ms", 30.0),
    }
    assert set(frame.dim_provider) == {"A"}


def test_long_metric_and_unit_columns(tmp_path: Path) -> None:
    d = DatasetDescriptor(
        name="pts",
        path="data.csv",
        shape="long",
        keys=["description"],
        metric_column="test",
        value_column="value",
        unit_column="scale",
    )
    text = "repetition,test,description,value,scale\n1,pts/x,Copy,5.0,MB/s\n"
    frame = read_dataset(d, _csv(tmp_path, text), CTX, LoadReport())
    assert frame is not None
    assert frame.iloc[0][["metric", "unit", "dim_description"]].tolist() == [
        "pts/x",
        "MB/s",
        "Copy",
    ]


def test_timeseries_melts_numeric_columns(tmp_path: Path) -> None:
    d = DatasetDescriptor(
        name="ps",
        path="data.csv",
        shape="timeseries",
        time_column="timestamp",
        fixed={"repetition": 1, "collector": "PSUtilCollector"},
    )
    text = "timestamp,cpu_percent,time,collector\n2026-10-08 22:43:18,86.3,22:43:18,PSUtilCollector\n"
    frame = read_dataset(d, _csv(tmp_path, text), CTX, LoadReport())
    assert frame is not None
    assert frame.columns.tolist() == [
        "run_id",
        "host",
        "workload",
        "repetition",
        "collector",
        "timestamp",
        "metric",
        "value",
    ]
    assert frame.iloc[0][["collector", "metric", "value"]].tolist() == [
        "PSUtilCollector",
        "cpu_percent",
        86.3,
    ]
    assert pd.api.types.is_datetime64_any_dtype(frame["timestamp"])


def test_host_info_keeps_text_values(tmp_path: Path) -> None:
    d = DatasetDescriptor(
        name="system_info",
        path="data.csv",
        shape="long",
        table="host_info",
        keys=["category", "name"],
        value_column="value",
    )
    frame = read_dataset(
        d,
        _csv(tmp_path, "category,name,value\ncpu,model,Cortex-X925\nmem,total,8\n"),
        CTX,
        LoadReport(),
    )
    assert frame is not None
    assert frame.columns.tolist() == ["run_id", "host", "category", "name", "value"]
    assert frame["value"].tolist() == ["Cortex-X925", "8"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest -q -p no:cacheprovider tests/unit/lb_analytics/test_unify_readers.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'lb_analytics.unify'`.

- [ ] **Step 3: Implement report and readers**

```python
# lb_analytics/unify/report.py
"""What a load did: files read, problems found, what was left out."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class LoadReport:
    files_read: list[str] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)
    undeclared_files: list[str] = field(default_factory=list)
    not_loadable: list[str] = field(default_factory=list)
    failed_repetitions: list[dict[str, Any]] = field(default_factory=list)
    ignored_columns: dict[str, list[str]] = field(default_factory=dict)
    missing_values: dict[str, int] = field(default_factory=dict)

    def error(self, source: str, message: str) -> None:
        self.errors.append({"source": source, "message": message})

    def warn(self, source: str, message: str) -> None:
        self.warnings.append({"source": source, "message": message})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
```

```python
# lb_analytics/unify/readers.py
"""Turn one declared dataset file into rows of a unified table."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from lb_analytics.unify.report import LoadReport
from lb_common.api import DatasetDescriptor, plan_wide

RESULTS_COLUMNS = [
    "run_id",
    "host",
    "workload",
    "plugin",
    "repetition",
    "dataset",
    "metric",
    "value",
    "unit",
]
SAMPLES_COLUMNS = [
    "run_id",
    "host",
    "workload",
    "repetition",
    "collector",
    "timestamp",
    "metric",
    "value",
]
HOST_INFO_COLUMNS = ["run_id", "host", "category", "name", "value"]


@dataclass(frozen=True)
class SourceContext:
    run_id: str
    host: str
    workload: str | None
    plugin: str | None


def read_dataset(
    descriptor: DatasetDescriptor, path: Path, ctx: SourceContext, report: LoadReport
) -> pd.DataFrame | None:
    """Read one file of ``descriptor`` into its target table's shape."""
    source = path.name
    try:
        frame = pd.read_csv(path)
    except Exception as exc:
        report.error(source, f"{descriptor.name}: cannot read CSV: {exc}")
        return None
    if descriptor.target_table == "host_info":
        return _host_info(descriptor, frame, ctx)
    if descriptor.shape == "timeseries":
        return _timeseries(descriptor, frame, ctx)
    long = (
        _wide(descriptor, frame, source, report)
        if descriptor.shape == "wide"
        else _long(descriptor, frame)
    )
    if long is None:
        return None
    return _finish_results(descriptor, long, ctx, source, report)


def _numeric(
    series: pd.Series, column: str, source: str, report: LoadReport
) -> pd.Series | None:
    values = pd.to_numeric(series, errors="coerce")
    bad = int((values.isna() & series.notna()).sum())
    if bad:
        report.error(source, f"column {column}: {bad} non-numeric values")
        return None
    return values.astype("float64")


def _wide(
    d: DatasetDescriptor, frame: pd.DataFrame, source: str, report: LoadReport
) -> pd.DataFrame | None:
    plan = plan_wide(d, list(frame.columns))
    for spec in plan.unmatched_specs:
        report.warn(source, f"{d.name}: metric {spec!r} matched no column")
    if plan.ignored:
        report.ignored_columns[source] = plan.ignored
    keys = [k for k in (*d.keys, "repetition") if k in frame.columns]
    pieces = []
    for mc in plan.metrics:
        values = _numeric(frame[mc.column], mc.column, source, report)
        if values is None:
            return None
        piece = frame[keys].copy()
        piece["metric"] = mc.metric
        piece["value"] = values
        piece["unit"] = (
            frame[mc.unit_column] if mc.unit_column in frame.columns else mc.unit
        )
        for dim, value in mc.dims.items():
            piece[f"dim_{dim}"] = value
        pieces.append(piece)
    if not pieces:
        return pd.DataFrame(columns=[*keys, "metric", "value", "unit"])
    return pd.concat(pieces, ignore_index=True)


def _long(d: DatasetDescriptor, frame: pd.DataFrame) -> pd.DataFrame:
    keys = [k for k in (*d.keys, "repetition") if k in frame.columns]
    if d.value_columns:
        pieces = []
        for vc in d.value_columns:
            piece = frame[keys].copy()
            piece["metric"] = vc.column
            piece["value"] = frame[vc.column]
            piece["unit"] = vc.unit
            pieces.append(piece)
        return pd.concat(pieces, ignore_index=True)
    assert d.metric_column is not None and d.value_column is not None
    piece = frame[keys].copy()
    piece["metric"] = frame[d.metric_column].astype("string")
    piece["value"] = frame[d.value_column]
    piece["unit"] = frame[d.unit_column] if d.unit_column else d.unit
    return piece


def _finish_results(
    d: DatasetDescriptor,
    frame: pd.DataFrame,
    ctx: SourceContext,
    source: str,
    report: LoadReport,
) -> pd.DataFrame | None:
    values = _numeric(frame["value"], "value", source, report)
    if values is None:
        return None
    frame = frame.assign(value=values)
    for key, value in d.fixed.items():
        frame[key] = value
    missing = int(frame["value"].isna().sum())
    if missing:
        report.missing_values[source] = report.missing_values.get(source, 0) + missing
    frame = frame[frame["value"].notna()]
    renames = {k: f"dim_{k}" for k in (*d.keys, *d.fixed) if k != "repetition"}
    frame = frame.rename(columns=renames)
    frame = frame.assign(
        run_id=ctx.run_id,
        host=ctx.host,
        workload=ctx.workload,
        plugin=ctx.plugin,
        dataset=d.name,
    )
    if "repetition" not in frame.columns:
        frame["repetition"] = pd.NA
    dims = sorted(c for c in frame.columns if c.startswith("dim_"))
    out = frame[RESULTS_COLUMNS + dims].copy()
    out["unit"] = out["unit"].astype("string")
    out["metric"] = out["metric"].astype("string")
    for dim in dims:
        out[dim] = out[dim].astype("string")
    out["repetition"] = pd.to_numeric(out["repetition"]).astype("Int64")
    return out.reset_index(drop=True)


def _timeseries(
    d: DatasetDescriptor, frame: pd.DataFrame, ctx: SourceContext
) -> pd.DataFrame:
    assert d.time_column is not None
    excluded = [re.compile(p) for p in d.exclude]
    metrics = [
        c
        for c in frame.columns
        if c != d.time_column
        and c not in d.keys
        and not any(p.fullmatch(c) for p in excluded)
        and pd.api.types.is_numeric_dtype(frame[c])
    ]
    melted = frame[[d.time_column, *metrics]].melt(
        id_vars=[d.time_column], var_name="metric", value_name="value"
    )
    melted = melted.rename(columns={d.time_column: "timestamp"})
    melted["timestamp"] = pd.to_datetime(melted["timestamp"], errors="coerce")
    melted = melted.assign(
        run_id=ctx.run_id,
        host=ctx.host,
        workload=ctx.workload,
        repetition=d.fixed.get("repetition", pd.NA),
        collector=str(d.fixed.get("collector", d.name)),
    )
    out = melted[SAMPLES_COLUMNS].copy()
    out["repetition"] = pd.to_numeric(out["repetition"]).astype("Int64")
    out["value"] = out["value"].astype("float64")
    out["metric"] = out["metric"].astype("string")
    return out[out["value"].notna()].reset_index(drop=True)


def _host_info(
    d: DatasetDescriptor, frame: pd.DataFrame, ctx: SourceContext
) -> pd.DataFrame:
    assert d.value_column is not None
    out = frame[[*d.keys, d.value_column]].astype("string")
    out = out.rename(columns={d.value_column: "value"})
    out.insert(0, "host", ctx.host)
    out.insert(0, "run_id", ctx.run_id)
    return out[HOST_INFO_COLUMNS].reset_index(drop=True)
```

Note: `_host_info` assumes keys are exactly `category`, `name` (the runner's `SYSTEM_INFO_DATASET`).

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest -q -p no:cacheprovider tests/unit/lb_analytics/test_unify_readers.py`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
uv run ruff check lb_analytics tests/unit/lb_analytics && uv run ruff format lb_analytics tests/unit/lb_analytics
git add lb_analytics/unify tests/unit/lb_analytics/test_unify_readers.py
git commit -m "Add the dataset readers of the analytics unification

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: `load_experiment`, Parquet output and public API

**Files:**
- Create: `lb_analytics/unify/loader.py`, `lb_analytics/unify/experiment.py`
- Modify: `lb_analytics/api.py`, `lb_app/api.py`, `pyproject.toml`, `uv.lock`, `docs/reference/analytics.md`
- Test: `tests/unit/lb_analytics/test_unify_loader.py`

**Interfaces:**
- Consumes: `read_dataset`, `SourceContext`, `LoadReport`, column constants (Task 7); `read_manifest`, `MANIFEST_FILENAME`, `RunInfo` (`lb_common.api`); manifests written by Task 6.
- Produces: `load_experiment(runs: Sequence[RunInfo]) -> ExperimentData`; `ExperimentData` dataclass with DataFrames `runs, host_info, repetitions, results, samples`, `report: LoadReport`, property `is_empty: bool`, method `to_parquet(out_dir: Path) -> list[Path]`. Exported from `lb_analytics.api` and `lb_app.api`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/lb_analytics/test_unify_loader.py
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from lb_analytics.api import load_experiment
from lb_common.api import RunInfo
from lb_plugins.api import create_registry
from lb_runner.api import write_host_manifest, write_workload_manifest

pytestmark = pytest.mark.unit_analytics

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "plugin_outputs"


def _run(
    root: Path, run_id: str, hosts: dict[str, list[str]], journal: bool = True
) -> RunInfo:
    """Lay out a collected run from the fixtures and write its manifests."""
    run_root = root / run_id
    for host, workloads in hosts.items():
        host_dir = run_root / host if host != "localhost" else run_root
        host_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(FIXTURES / "_host" / "system_info.csv", host_dir)
        write_host_manifest(host_dir)
        for workload in workloads:
            work = host_dir / workload
            shutil.copytree(FIXTURES / workload, work)
            plugin = create_registry().get(workload)
            results = json.loads((work / f"{workload}_results.json").read_text())
            plugin.export_results_to_csv(results, work, run_id, workload)
            write_workload_manifest(plugin, work, workload)
    if journal:
        shutil.copy(FIXTURES / "_run" / "run_journal.json", run_root)
    return RunInfo(
        run_id=run_id,
        output_root=run_root,
        report_root=None,
        data_export_root=None,
        hosts=list(hosts),
        workloads=[],
        created_at=None,
        journal_path=None,
    )


def test_two_runs_two_hosts_unify_into_five_tables(tmp_path: Path) -> None:
    runs = [
        _run(tmp_path, "r1", {"h1": ["stress_ng", "fio"], "h2": ["stress_ng"]}),
        _run(tmp_path, "r2", {"h1": ["yabs", "pts_compress_7zip", "dfaas"]}),
    ]
    data = load_experiment(runs)
    assert not data.report.errors, data.report.errors
    assert not data.report.undeclared_files
    assert set(data.runs.run_id) == {"r1", "r2"}
    assert set(data.host_info.host) == {"h1", "h2"}
    stress = data.results[
        (data.results.workload == "stress_ng") & (data.results.host == "h1")
    ]
    cpu_ops = stress[(stress.metric == "bogo_ops") & (stress.dim_stressor == "cpu")]
    assert cpu_ops.iloc[0]["value"] == pytest.approx(18800.0)
    assert set(data.results[data.results.workload == "yabs"].dataset) == {
        "yabs_plugin",
        "yabs_iperf",
    }
    assert {"dim_config_id", "dim_function"} <= set(data.results.columns)
    assert set(data.samples.collector) == {"PSUtilCollector", "CLICollector"}
    assert set(data.repetitions.columns) >= {
        "run_id",
        "host",
        "workload",
        "repetition",
        "success",
    }


def test_absent_dimensions_are_real_nulls(tmp_path: Path) -> None:
    data = load_experiment([_run(tmp_path, "r1", {"h1": ["stress_ng", "fio"]})])
    fio = data.results[data.results.workload == "fio"]
    assert fio["dim_stressor"].isna().all()
    assert not (fio["dim_stressor"].astype(str) == "nan").any()


def test_local_layout_is_attributed_to_localhost(tmp_path: Path) -> None:
    data = load_experiment([_run(tmp_path, "r1", {"localhost": ["fio"]})])
    assert set(data.results.host) == {"localhost"}
    assert set(data.host_info.host) == {"localhost"}


def test_missing_declared_file_fails_only_its_dataset(tmp_path: Path) -> None:
    run = _run(tmp_path, "r1", {"h1": ["yabs"]})
    (run.output_root / "h1" / "yabs" / "yabs_iperf.csv").unlink()
    data = load_experiment([run])
    assert any("yabs_iperf" in e["message"] for e in data.report.errors)
    assert "yabs_plugin" in set(data.results.dataset)


def test_run_without_journal_still_loads(tmp_path: Path) -> None:
    data = load_experiment([_run(tmp_path, "r1", {"h1": ["fio"]}, journal=False)])
    assert data.runs.iloc[0]["run_id"] == "r1"
    assert pd.isna(data.runs.iloc[0]["config_hash"])
    assert any("run_journal.json" in w["message"] for w in data.report.warnings)
    assert not data.results.empty


def test_workload_without_manifest_is_not_loadable(tmp_path: Path) -> None:
    run = _run(tmp_path, "r1", {"h1": ["fio"]})
    (run.output_root / "h1" / "fio" / "datasets.json").unlink()
    data = load_experiment([run])
    assert data.report.not_loadable == [str(run.output_root / "h1" / "fio")]
    assert data.is_empty


def test_undeclared_csv_is_reported(tmp_path: Path) -> None:
    run = _run(tmp_path, "r1", {"h1": ["fio"]})
    (run.output_root / "h1" / "fio" / "extra.csv").write_text("a\n1\n")
    data = load_experiment([run])
    assert data.report.undeclared_files == [
        str(run.output_root / "h1" / "fio" / "extra.csv")
    ]


def test_parquet_round_trip(tmp_path: Path) -> None:
    data = load_experiment([_run(tmp_path, "r1", {"h1": ["stress_ng"]})])
    paths = data.to_parquet(tmp_path / "out")
    assert sorted(p.name for p in paths) == [
        "host_info.parquet",
        "load_report.json",
        "repetitions.parquet",
        "results.parquet",
        "runs.parquet",
        "samples.parquet",
    ]
    back = pd.read_parquet(tmp_path / "out" / "results.parquet")
    assert len(back) == len(data.results)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest -q -p no:cacheprovider tests/unit/lb_analytics/test_unify_loader.py`
Expected: FAIL with `ImportError: cannot import name 'load_experiment' from 'lb_analytics.api'`.

- [ ] **Step 3: Add pyarrow**

In `pyproject.toml`, add `"pyarrow>=17.0.0",` to the `controller` extra, and extend the deptry comment above the `"pyarrow"` DEP002 entry:

```toml
    # Not imported in Python at all, but required at runtime: duckdb uses
    # pyarrow for its parquet reader/writer, which the peva_faas memory
    # checkpoint relies on (read_parquet / COPY ... FORMAT PARQUET), and
    # pandas uses it as the to_parquet engine for lb_analytics exports.
    "pyarrow",
```

Run: `uv lock && uv sync --all-extras`
Expected: `uv.lock` updated, no resolution errors.

- [ ] **Step 4: Implement the loader**

```python
# lb_analytics/unify/experiment.py
"""The unified tables of an experiment."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from lb_analytics.unify.report import LoadReport

TABLES = ("runs", "host_info", "repetitions", "results", "samples")


@dataclass
class ExperimentData:
    runs: pd.DataFrame
    host_info: pd.DataFrame
    repetitions: pd.DataFrame
    results: pd.DataFrame
    samples: pd.DataFrame
    report: LoadReport

    @property
    def is_empty(self) -> bool:
        return self.results.empty and self.samples.empty

    def to_parquet(self, out_dir: Path) -> list[Path]:
        """Write one Parquet file per table plus ``load_report.json``."""
        out_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        for name in TABLES:
            path = out_dir / f"{name}.parquet"
            getattr(self, name).to_parquet(path, index=False)
            paths.append(path)
        report_path = out_dir / "load_report.json"
        report_path.write_text(json.dumps(self.report.to_dict(), indent=2))
        paths.append(report_path)
        return paths
```

```python
# lb_analytics/unify/loader.py
"""Find every manifest of a set of runs and build the unified tables."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from lb_analytics.unify.experiment import ExperimentData
from lb_analytics.unify.readers import (
    HOST_INFO_COLUMNS,
    RESULTS_COLUMNS,
    SAMPLES_COLUMNS,
    SourceContext,
    read_dataset,
)
from lb_analytics.unify.report import LoadReport
from lb_common.api import MANIFEST_FILENAME, DatasetManifest, RunInfo, read_manifest

RUNS_COLUMNS = ["run_id", "experiment_id", "created_at", "config_hash", "repetitions"]
REPETITION_COLUMNS = [
    "run_id",
    "host",
    "workload",
    "plugin",
    "repetition",
    "success",
    "start_time",
    "end_time",
    "duration_seconds",
]


def load_experiment(runs: Sequence[RunInfo]) -> ExperimentData:
    """Load every declared dataset of ``runs`` into unified tables."""
    report = LoadReport()
    frames: dict[str, list[pd.DataFrame]] = {
        "results": [],
        "samples": [],
        "host_info": [],
    }
    run_rows: list[dict[str, Any]] = []
    repetition_rows: list[dict[str, Any]] = []
    for run in runs:
        root = run.output_root
        run_rows.append(_run_row(run, report))
        for manifest_dir in _manifest_dirs(root):
            try:
                manifest = read_manifest(manifest_dir)
            except Exception as exc:
                report.error(str(manifest_dir), f"invalid {MANIFEST_FILENAME}: {exc}")
                continue
            ctx = SourceContext(
                run.run_id,
                _host_of(root, manifest_dir, manifest),
                manifest.workload,
                manifest.plugin,
            )
            _load_manifest(manifest, manifest_dir, ctx, frames, report)
            repetition_rows.extend(_repetitions(manifest, manifest_dir, ctx, report))
        _report_unmanifested(root, report)
    return ExperimentData(
        runs=_runs_frame(run_rows),
        host_info=_concat(frames["host_info"], HOST_INFO_COLUMNS),
        repetitions=pd.DataFrame(repetition_rows, columns=REPETITION_COLUMNS),
        results=_concat(frames["results"], RESULTS_COLUMNS),
        samples=_concat(frames["samples"], SAMPLES_COLUMNS),
        report=report,
    )


def _manifest_dirs(root: Path) -> list[Path]:
    found = [
        *root.glob(MANIFEST_FILENAME),
        *root.glob(f"*/{MANIFEST_FILENAME}"),
        *root.glob(f"*/*/{MANIFEST_FILENAME}"),
    ]
    return sorted(p.parent for p in found)


def _host_of(root: Path, manifest_dir: Path, manifest: DatasetManifest) -> str:
    host_dir = manifest_dir.parent if manifest.workload else manifest_dir
    return "localhost" if host_dir == root else host_dir.name


def _load_manifest(
    manifest: DatasetManifest,
    manifest_dir: Path,
    ctx: SourceContext,
    frames: dict[str, list[pd.DataFrame]],
    report: LoadReport,
) -> None:
    for descriptor in manifest.datasets:
        if descriptor.target_table == "ignore":
            continue
        files = sorted(manifest_dir.glob(descriptor.path))
        if not files:
            report.error(
                str(manifest_dir),
                f"{descriptor.name}: declared file {descriptor.path!r} not found",
            )
            continue
        for path in files:
            frame = read_dataset(descriptor, path, ctx, report)
            if frame is not None:
                frames[descriptor.target_table].append(frame)
                report.files_read.append(str(path))
    _report_undeclared(manifest, manifest_dir, report)


def _report_undeclared(
    manifest: DatasetManifest, manifest_dir: Path, report: LoadReport
) -> None:
    declared = {p for d in manifest.datasets for p in manifest_dir.glob(d.path)}
    # A host manifest owns only its own directory; workload ones own their tree.
    candidates = (
        manifest_dir.rglob("*.csv") if manifest.workload else manifest_dir.glob("*.csv")
    )
    report.undeclared_files.extend(
        str(p) for p in sorted(candidates) if p not in declared
    )


def _report_unmanifested(root: Path, report: LoadReport) -> None:
    for results_file in sorted(
        [*root.glob("*/*_results.json"), *root.glob("*/*/*_results.json")]
    ):
        if not (results_file.parent / MANIFEST_FILENAME).exists():
            report.not_loadable.append(str(results_file.parent))


def _repetitions(
    manifest: DatasetManifest,
    manifest_dir: Path,
    ctx: SourceContext,
    report: LoadReport,
) -> list[dict[str, Any]]:
    if not manifest.repetitions:
        return []
    path = manifest_dir / manifest.repetitions
    try:
        entries = json.loads(path.read_text())
    except Exception as exc:
        report.error(str(path), f"cannot read repetitions: {exc}")
        return []
    rows = []
    for entry in entries:
        row = {
            "run_id": ctx.run_id,
            "host": ctx.host,
            "workload": ctx.workload,
            "plugin": ctx.plugin,
            **{k: entry.get(k) for k in REPETITION_COLUMNS[4:]},
        }
        rows.append(row)
        if row["success"] is False:
            report.failed_repetitions.append(
                {k: row[k] for k in ("run_id", "host", "workload", "repetition")}
            )
    return rows


def _run_row(run: RunInfo, report: LoadReport) -> dict[str, Any]:
    journal = run.output_root / "run_journal.json"
    metadata: dict[str, Any] = {}
    try:
        metadata = json.loads(journal.read_text()).get("metadata", {})
    except Exception as exc:
        report.warn(str(run.output_root), f"run_journal.json unreadable: {exc}")
    return {
        "run_id": run.run_id,
        "experiment_id": metadata.get("experiment_id"),
        "created_at": metadata.get("created_at"),
        "config_hash": metadata.get("config_hash"),
        "repetitions": metadata.get("repetitions"),
    }


def _runs_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=RUNS_COLUMNS)
    frame["created_at"] = pd.to_datetime(frame["created_at"], errors="coerce")
    return frame


def _concat(frames: list[pd.DataFrame], columns: list[str]) -> pd.DataFrame:
    if not frames:
        return pd.DataFrame(columns=columns)
    out = pd.concat(frames, ignore_index=True)
    # Frames without a given dimension leave it missing: keep it a string column
    # of real nulls rather than letting concat fall back to object/NaN.
    for column in out.columns:
        if column.startswith("dim_"):
            out[column] = out[column].astype("string")
    return out
```


Export from `lb_analytics/api.py`:

```python
from lb_analytics.unify.experiment import ExperimentData
from lb_analytics.unify.loader import load_experiment
from lb_analytics.unify.report import LoadReport
```

(add `"ExperimentData"`, `"LoadReport"`, `"load_experiment"` to `__all__`). Re-export the same three names from `lb_app/api.py` next to `AnalyticsService`.

Append to `docs/reference/analytics.md`:

```markdown
## Unified datasets

`load_experiment(runs)` reads every `datasets.json` manifest of the given runs
and returns `runs`, `host_info`, `repetitions`, `results` and `samples` as pandas
DataFrames plus a `LoadReport`; `ExperimentData.to_parquet(dir)` writes them.

::: lb_analytics.unify.loader.load_experiment
::: lb_analytics.unify.experiment.ExperimentData
```

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest -q -p no:cacheprovider tests/unit/lb_analytics`
Expected: PASS (8 loader tests plus the existing analytics suite).

- [ ] **Step 6: Lint, boundaries and commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run basedpyright && uv run lint-imports && uv run python scripts/check_api_imports.py
git add lb_analytics lb_app/api.py pyproject.toml uv.lock docs/reference/analytics.md tests/unit/lb_analytics/test_unify_loader.py
git commit -m "Add load_experiment: unified tables and Parquet export

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Every plugin is declared

**Files:**
- Test: `tests/unit/lb_plugins/test_dataset_declarations.py`

**Interfaces:**
- Consumes: `DECLARED` (Tasks 2–5).

- [ ] **Step 1: Add the completeness test**

```python
# Same plugin class as pts_ramspeed and covered by its declaration; no fixture.
SAME_CLASS_AS_DECLARED = {"pts_blosc", "pts_gmpbench", "pts_build_linux_kernel"}


def test_every_registered_plugin_is_declared() -> None:
    registered = set(create_registry().available())
    assert registered - SAME_CLASS_AS_DECLARED == set(DECLARED)
```

- [ ] **Step 2: Run the whole unit suite and the hooks**

Run: `uv run pytest -q -p no:cacheprovider tests/unit && uv run pre-commit run --all-files`
Expected: both exit 0.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/lb_plugins/test_dataset_declarations.py
git commit -m "Require every registered plugin to declare its datasets

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Real verification on Multipass with reconciliation

**Files:** none in the repo; the script lives in the session scratchpad.

**Interfaces:**
- Consumes: the verification harness `verify_plugin.py` used on 2026-10-08 (session scratchpad), `load_experiment`, `plan_wide`, `read_manifest`.

- [ ] **Step 1: Re-run every plugin except Geekbench on a fresh VM**

Launch `lb-worker-verify` as on 2026-10-08 and run `verify_plugin.py` for `baseline, dd, fio, hpl, stream, stress_ng, sysbench, unixbench, yabs, pts_ramspeed, pts_gmpbench, pts_blosc, pts_compress_7zip, pts_build_linux_kernel`; then launch the two FaaS VMs and run `dfaas` and `peva_faas` (peva_faas with a fresh `memory.db_path`). Each run must report `NO PROBLEMS` and its local tree must now contain `datasets.json` at host and workload level.

- [ ] **Step 2: Unify and reconcile**

```python
from pathlib import Path

import pandas as pd

from lb_analytics.api import load_experiment
from lb_common.api import RunInfo, plan_wide, read_manifest

runs = [
    RunInfo(
        run_id=p.name,
        output_root=p,
        report_root=None,
        data_export_root=None,
        hosts=[],
        workloads=[],
        created_at=None,
        journal_path=None,
    )
    for p in sorted(Path(SCRATCH / "runs").glob("*/results/*"))
]
data = load_experiment(runs)
assert not data.report.errors, data.report.errors
assert not data.report.undeclared_files, data.report.undeclared_files

expected = 0
for manifest_path in Path(SCRATCH / "runs").glob("*/results/*/*/*/datasets.json"):
    manifest = read_manifest(manifest_path.parent)
    for d in manifest.datasets:
        if d.target_table != "results":
            continue
        for f in manifest_path.parent.glob(d.path):
            frame = pd.read_csv(f)
            if d.shape == "wide":
                cols = [m.column for m in plan_wide(d, list(frame.columns)).metrics]
            elif d.value_columns:
                cols = [v.column for v in d.value_columns]
            else:
                cols = [d.value_column]
            expected += int(frame[cols].notna().sum().sum())
assert expected == len(data.results), (expected, len(data.results))
assert len(data.repetitions) == sum(
    len(
        __import__("json").loads(
            (p.parent / read_manifest(p.parent).repetitions).read_text()
        )
    )
    for p in Path(SCRATCH / "runs").glob("*/results/*/*/*/datasets.json")
)
data.to_parquet(SCRATCH / "unified")
```

Expected: both assertions hold; `SCRATCH/unified` holds the five Parquet files and `load_report.json`.

- [ ] **Step 3: Delete the VMs**

```bash
multipass delete lb-worker-verify lb-worker-dfaas-target lb-worker-dfaas-k6 --purge
```
