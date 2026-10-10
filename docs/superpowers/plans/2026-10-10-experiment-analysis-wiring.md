# Experiment analysis wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put experiment unification (sub-projects A and B) in front of the user in the CLI, TUI and GUI through one `lb_app` service, and remove the per-run `aggregate` analytics.

**Architecture:** `ExperimentData.filter` (lb_analytics) → `UnificationService` + `UnificationPreview` (lb_app) → a TUI flow module (lb_ui/flows/unification.py) used by `lb runs analyze`, `lb runs list` and the end of `lb run` → the GUI analytics view-model calls the same service through a generic background worker. The old aggregate path is deleted last, once nothing uses it.

**Tech Stack:** Python 3.12, pandas + pyarrow (Parquet), Typer + Rich (CLI/TUI), PySide6 (GUI), pytest.

**Spec:** docs/superpowers/specs/2026-10-10-experiment-analysis-wiring-design.md

## Global Constraints

- Imports across packages only through `*.api` (ruff TID251); `lb_analytics` imports only `lb_common`.
- Output folder: `<config data_export_dir>/<experiment id>/`, one Parquet per table plus `load_report.json`.
- Every user-facing failure is a `UnificationError`; CLI exit code 1 for it, 0 when written (load errors only warn).
- The equivalent command is shell-quoted (`shlex.join`) and carries `--root`, `--config` when known, and the filters.
- End-of-run prompt defaults to **No**; `--analyze` never asks.
- Test markers: `unit_analytics` for lb_analytics/lb_app service tests, `unit_ui` for lb_ui, `unit` for lb_gui.
- All pre-commit hooks green (`uv run pre-commit run --all-files`), whole unit suite green.

## Review Focus

- An experiment with a load error (unreadable CSV): the summary lists it, writing proceeds, `lb runs analyze` exits 0 with a warning — pinned in Task 3.
- Filters: deselecting everything in the TUI pick-many keeps the previous filter instead of meaning "all" or "none"; a host filter matching nothing gives "Nothing to unify", exit 1 — pinned in Task 3.
- A folder named like an experiment (folder `tuning` holding experiment `tuning`): the picker distinguishes them (`folder:` / `experiment:` item ids) — pinned in Task 3.
- Unifying again with a narrower filter leaves no stale data: every table file is rewritten — pinned in Task 2.
- `lb run --analyze` when unification fails after a completed run exits 1; the interactive prompt path never changes the exit code — pinned in Task 4.

---

### Task 1: `ExperimentData.filter` and `row_counts`

**Files:**
- Modify: `lb_analytics/unify/experiment.py`
- Test: `tests/unit/lb_analytics/test_experiment_filter.py`

**Interfaces:**
- Produces: `ExperimentData.filter(hosts: Sequence[str] = (), workloads: Sequence[str] = ()) -> ExperimentData`; `ExperimentData.row_counts -> dict[str, int]` (table name → rows, in `TABLES` order).

- [ ] **Step 1: Write the failing tests**

```python
import pandas as pd
import pytest

from lb_analytics.api import ExperimentData, LoadReport

pytestmark = pytest.mark.unit_analytics


def _data() -> ExperimentData:
    rows = [("r", h, w) for h in ("h1", "h2") for w in ("fio", "dd")]
    frame = pd.DataFrame(rows, columns=["run_id", "host", "workload"])
    return ExperimentData(
        runs=pd.DataFrame({"run_id": ["r"]}),
        host_info=pd.DataFrame({"run_id": ["r", "r"], "host": ["h1", "h2"]}),
        repetitions=frame,
        results=frame,
        samples=frame,
        report=LoadReport(),
    )


def test_no_filter_keeps_everything() -> None:
    data = _data().filter()
    assert data.row_counts == {
        "runs": 1,
        "host_info": 2,
        "repetitions": 4,
        "results": 4,
        "samples": 4,
    }


def test_host_filter_applies_to_every_table_with_a_host() -> None:
    data = _data().filter(hosts=["h1"])
    assert set(data.host_info.host) == {"h1"}
    assert set(data.repetitions.host) == {"h1"}
    assert set(data.results.host) == {"h1"}
    assert set(data.samples.host) == {"h1"}
    assert len(data.runs) == 1


def test_workload_filter_leaves_host_info_alone() -> None:
    data = _data().filter(workloads=["fio"])
    assert set(data.results.workload) == {"fio"}
    assert len(data.host_info) == 2


def test_both_filters_combine() -> None:
    data = _data().filter(hosts=["h2"], workloads=["dd"])
    assert data.results[["host", "workload"]].values.tolist() == [["h2", "dd"]]
    assert data.results.index.tolist() == [0]


def test_filter_keeps_the_load_report() -> None:
    original = _data()
    assert original.filter(hosts=["h1"]).report is original.report
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest -q -p no:cacheprovider tests/unit/lb_analytics/test_experiment_filter.py`
Expected: FAIL with `AttributeError: 'ExperimentData' object has no attribute 'filter'`

- [ ] **Step 3: Implement** — in `lb_analytics/unify/experiment.py` add `from collections.abc import Sequence` and, in `ExperimentData` after `is_empty`:

```python
@property
def row_counts(self) -> dict[str, int]:
    return {name: len(getattr(self, name)) for name in TABLES}


def filter(
    self, hosts: Sequence[str] = (), workloads: Sequence[str] = ()
) -> ExperimentData:
    """Keep the given hosts and workloads; an empty filter keeps everything.

    A filter applies to every table that has its column, so ``runs`` is
    never filtered and ``host_info`` only by host.
    """
    tables: dict[str, pd.DataFrame] = {}
    for name in TABLES:
        frame = getattr(self, name)
        if hosts and "host" in frame.columns:
            frame = frame[frame["host"].isin(hosts)]
        if workloads and "workload" in frame.columns:
            frame = frame[frame["workload"].isin(workloads)]
        tables[name] = frame.reset_index(drop=True)
    return ExperimentData(**tables, report=self.report)
```

- [ ] **Step 4: Run them to verify they pass**

Run: `uv run pytest -q -p no:cacheprovider tests/unit/lb_analytics/test_experiment_filter.py`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add lb_analytics/unify/experiment.py tests/unit/lb_analytics/test_experiment_filter.py
git commit -m "Filter unified experiment tables by host and workload"
```

---

### Task 2: `UnificationService` in lb_app

**Files:**
- Create: `lb_app/services/unification_service.py`
- Create: `tests/helpers/analytics_runs.py` (shared run builder, moved out of B's link test)
- Modify: `lb_app/api.py` (exports), `tests/unit/lb_app/test_experiment_to_analytics.py` (use the shared builder)
- Test: `tests/unit/lb_app/test_unification_service.py`

**Interfaces:**
- Consumes: `ExperimentData.filter`, `ExperimentData.row_counts` (Task 1); `RunCatalogService.list_experiments/get_experiment/folder_experiment/output_dir` and `ExperimentInfo` (B).
- Produces (all exported from `lb_app.api`):
  - `UnificationError(Exception)`
  - `UnificationPreview` (frozen dataclass): `experiment: ExperimentInfo`, `data: ExperimentData`, `hosts: tuple[str, ...]`, `workloads: tuple[str, ...]`, `out_dir: Path`, `command: str`; properties `row_counts: dict[str, int]`, `is_empty: bool`; method `summary_rows() -> list[tuple[str, str]]`.
  - `UnificationService(catalog: RunCatalogService, export_root: Path, config_path: Path | None = None)` with `output_dir: Path` (property), `list_targets() -> list[ExperimentInfo]`, `find(experiment_id: str | None) -> ExperimentInfo`, `prepare(experiment: ExperimentInfo, hosts: Sequence[str] = (), workloads: Sequence[str] = ()) -> UnificationPreview`, `write(preview: UnificationPreview) -> list[Path]`.
  - `tests.helpers.analytics_runs.collected_run(root: Path, run_id: str, experiment: str | None, workload: str, created_at: str = "2026-10-09T10:00:00", host: str = "h1") -> None`.

- [ ] **Step 1: Move the run builder to `tests/helpers/analytics_runs.py`**

```python
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
```

In `tests/unit/lb_app/test_experiment_to_analytics.py` delete `FIXTURES`, `_collected_run` and the now-unused imports (`json`, `shutil`, `create_registry`, `write_host_manifest`, `write_workload_manifest`), import `from tests.helpers.analytics_runs import collected_run`, and call `collected_run(...)` in place of `_collected_run(...)`.

Run: `uv run pytest -q -p no:cacheprovider tests/unit/lb_app/test_experiment_to_analytics.py`
Expected: 1 passed

- [ ] **Step 2: Write the failing tests** — `tests/unit/lb_app/test_unification_service.py`

```python
from pathlib import Path

import pandas as pd
import pytest

from lb_app.api import RunCatalogService, UnificationError, UnificationService
from lb_app.services import unification_service
from tests.helpers.analytics_runs import collected_run

pytestmark = pytest.mark.unit_analytics


@pytest.fixture
def root(tmp_path: Path) -> Path:
    root = tmp_path / "benchmark_results"
    collected_run(root, "run-1", "tuning", "fio", "2026-10-09T10:00:00")
    collected_run(root, "run-2", "tuning", "stress_ng", "2026-10-09T11:00:00")
    collected_run(root, "run-3", "other", "dd", "2026-10-09T09:00:00")
    return root


def _service(root: Path, tmp_path: Path, config: Path | None = None):
    return UnificationService(
        RunCatalogService(root), tmp_path / "exports", config_path=config
    )


def test_targets_are_experiments_newest_first_then_the_folder(root, tmp_path):
    targets = _service(root, tmp_path).list_targets()
    assert [(t.kind, t.id) for t in targets] == [
        ("experiment", "tuning"),
        ("experiment", "other"),
        ("folder", "benchmark_results"),
    ]


def test_an_empty_folder_has_no_targets_and_find_explains(tmp_path):
    service = _service(tmp_path / "missing", tmp_path)
    assert service.list_targets() == []
    with pytest.raises(UnificationError, match="No runs in"):
        service.find(None)


def test_find_names_recent_experiments_for_an_unknown_id(root, tmp_path):
    with pytest.raises(UnificationError, match="'nope' not found.*tuning, other"):
        _service(root, tmp_path).find("nope")


def test_find_none_is_the_folder(root, tmp_path):
    folder = _service(root, tmp_path).find(None)
    assert folder.kind == "folder"
    assert len(folder.runs) == 3


def test_prepare_loads_the_experiment_and_writes_it(root, tmp_path):
    service = _service(root, tmp_path)
    preview = service.prepare(service.find("tuning"))
    assert preview.out_dir == tmp_path / "exports" / "tuning"
    assert preview.row_counts["runs"] == 2
    assert not preview.is_empty
    paths = service.write(preview)
    assert {p.name for p in paths} >= {"results.parquet", "load_report.json"}
    results = pd.read_parquet(tmp_path / "exports" / "tuning" / "results.parquet")
    assert set(results.workload) == {"fio", "stress_ng"}


def test_selecting_everything_is_no_filter(root, tmp_path):
    service = _service(root, tmp_path)
    tuning = service.find("tuning")
    preview = service.prepare(tuning, hosts=["h1"], workloads=tuning.workloads)
    assert preview.hosts == ()
    assert preview.workloads == ()


def test_a_narrower_unification_rewrites_every_table(root, tmp_path):
    service = _service(root, tmp_path)
    tuning = service.find("tuning")
    service.write(service.prepare(tuning))
    service.write(service.prepare(tuning, workloads=["fio"]))
    out = tmp_path / "exports" / "tuning"
    assert set(pd.read_parquet(out / "results.parquet").workload) == {"fio"}
    assert set(pd.read_parquet(out / "samples.parquet").workload) <= {"fio"}
    assert set(pd.read_parquet(out / "repetitions.parquet").workload) == {"fio"}


def test_an_empty_preview_is_refused(root, tmp_path):
    service = _service(root, tmp_path)
    preview = service.prepare(service.find("tuning"), hosts=["nobody"])
    assert preview.is_empty
    assert ("Nothing to unify", "no results or samples after the filters") in (
        preview.summary_rows()
    )
    with pytest.raises(UnificationError, match="Nothing to unify"):
        service.write(preview)
    assert not (tmp_path / "exports" / "tuning").exists()


def test_the_equivalent_command_reproduces_the_choice(root, tmp_path):
    service = _service(root, tmp_path, config=tmp_path / "my config.yaml")
    tuning = service.find("tuning")
    preview = service.prepare(tuning, workloads=["fio"])
    assert preview.command == (
        f"lb runs analyze --experiment tuning --root {root} "
        f"--config '{tmp_path / 'my config.yaml'}' --workload fio"
    )
    folder = service.prepare(service.find(None))
    assert folder.command.startswith("lb runs analyze --folder --root ")


def test_summary_rows_cover_what_the_user_decides_on(root, tmp_path):
    service = _service(root, tmp_path)
    rows = dict(service.prepare(service.find("tuning")).summary_rows())
    assert rows["Experiment"] == "tuning"
    assert rows["Runs"] == "2"
    assert rows["Workloads"] == "fio, stress_ng"
    assert rows["Rows: runs"] == "2"
    assert rows["Load errors"] == "0"
    assert rows["Output"] == str(tmp_path / "exports" / "tuning")


def test_missing_pyarrow_is_reported_before_loading(root, tmp_path, monkeypatch):
    monkeypatch.setattr(unification_service, "_has_pyarrow", lambda: False)
    service = _service(root, tmp_path)
    with pytest.raises(UnificationError, match=r"linux-benchmark-lib\[controller\]"):
        service.prepare(service.find("tuning"))
```

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest -q -p no:cacheprovider tests/unit/lb_app/test_unification_service.py`
Expected: FAIL at collection: `ImportError: cannot import name 'UnificationError' from 'lb_app.api'`

- [ ] **Step 4: Implement** — `lb_app/services/unification_service.py`

```python
"""Unify an experiment's datasets into Parquet tables, for every UI."""

from __future__ import annotations

import importlib.util
import shlex
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from lb_analytics.api import ExperimentData, load_experiment
from lb_common.api import ExperimentInfo
from lb_controller.api import RunCatalogService


class UnificationError(Exception):
    """A user-facing reason the unification cannot go ahead."""


@dataclass(frozen=True)
class UnificationPreview:
    """What a unification will write, loaded once and shown before writing."""

    experiment: ExperimentInfo
    data: ExperimentData
    hosts: tuple[str, ...]
    workloads: tuple[str, ...]
    out_dir: Path
    command: str

    @property
    def row_counts(self) -> dict[str, int]:
        return self.data.row_counts

    @property
    def is_empty(self) -> bool:
        return self.data.is_empty

    def summary_rows(self) -> list[tuple[str, str]]:
        """Label/value pairs every UI shows before the user confirms."""
        report = self.data.report
        hosts = self.hosts or self.experiment.hosts
        workloads = self.workloads or self.experiment.workloads
        rows = [
            ("Experiment", self.experiment.id),
            ("Kind", self.experiment.kind),
            ("Runs", str(len(self.experiment.runs))),
            ("Hosts", ", ".join(hosts) or "-"),
            ("Workloads", ", ".join(workloads) or "-"),
        ]
        rows += [(f"Rows: {name}", str(n)) for name, n in self.row_counts.items()]
        rows += [
            ("Failed repetitions", str(len(report.failed_repetitions))),
            ("Load errors", str(len(report.errors))),
            ("Load warnings", str(len(report.warnings))),
        ]
        rows += [(f"Error: {e['source']}", e["message"]) for e in report.errors]
        if self.is_empty:
            rows.append(("Nothing to unify", "no results or samples after the filters"))
        rows.append(("Output", str(self.out_dir)))
        return rows


class UnificationService:
    """List experiments, preview their unification, write it."""

    def __init__(
        self,
        catalog: RunCatalogService,
        export_root: Path,
        config_path: Path | None = None,
    ) -> None:
        self._catalog = catalog
        self._export_root = export_root
        self._config_path = config_path

    @property
    def output_dir(self) -> Path:
        return self._catalog.output_dir

    def list_targets(self) -> list[ExperimentInfo]:
        """Experiments newest first, then the whole folder; [] without runs."""
        experiments = self._catalog.list_experiments()
        if not experiments:
            return []
        return [*experiments, self._catalog.folder_experiment()]

    def find(self, experiment_id: str | None) -> ExperimentInfo:
        """The named experiment, or the whole folder for ``None``."""
        if experiment_id is None:
            folder = self._catalog.folder_experiment()
            if not folder.runs:
                raise UnificationError(f"No runs in {self.output_dir}")
            return folder
        found = self._catalog.get_experiment(experiment_id)
        if found is None:
            recent = [e.id for e in self._catalog.list_experiments()[:5]]
            hint = f"; recent experiments: {', '.join(recent)}" if recent else ""
            raise UnificationError(
                f"Experiment {experiment_id!r} not found in {self.output_dir}{hint}"
            )
        return found

    def prepare(
        self,
        experiment: ExperimentInfo,
        hosts: Sequence[str] = (),
        workloads: Sequence[str] = (),
    ) -> UnificationPreview:
        """Load and filter the experiment; nothing is written yet."""
        if not _has_pyarrow():
            raise UnificationError(
                "Writing Parquet needs pyarrow: "
                "pip install 'linux-benchmark-lib[controller]'"
            )
        host_filter = _effective(hosts, experiment.hosts)
        workload_filter = _effective(workloads, experiment.workloads)
        data = load_experiment(experiment.runs).filter(host_filter, workload_filter)
        return UnificationPreview(
            experiment=experiment,
            data=data,
            hosts=host_filter,
            workloads=workload_filter,
            out_dir=self._export_root / experiment.id,
            command=self._command(experiment, host_filter, workload_filter),
        )

    def write(self, preview: UnificationPreview) -> list[Path]:
        """Write the previewed tables, replacing an earlier unification."""
        if preview.is_empty:
            raise UnificationError(
                f"Nothing to unify for {preview.experiment.id}: "
                "no results or samples after the filters"
            )
        return preview.data.to_parquet(preview.out_dir)

    def _command(
        self,
        experiment: ExperimentInfo,
        hosts: Sequence[str],
        workloads: Sequence[str],
    ) -> str:
        args = ["lb", "runs", "analyze"]
        if experiment.kind == "folder":
            args.append("--folder")
        else:
            args += ["--experiment", experiment.id]
        args += ["--root", str(self.output_dir)]
        if self._config_path is not None:
            args += ["--config", str(self._config_path)]
        for host in hosts:
            args += ["--host", host]
        for workload in workloads:
            args += ["--workload", workload]
        return shlex.join(args)


def _effective(selected: Sequence[str], available: Sequence[str]) -> tuple[str, ...]:
    """The filter to apply: empty when everything available is selected."""
    chosen = tuple(sorted(set(selected)))
    return () if set(chosen) >= set(available) else chosen


def _has_pyarrow() -> bool:
    return importlib.util.find_spec("pyarrow") is not None
```

In `lb_app/api.py` add

```python
from lb_app.services.unification_service import (
    UnificationError,
    UnificationPreview,
    UnificationService,
)
```

and add `"UnificationError"`, `"UnificationPreview"`, `"UnificationService"` to `__all__` (kept sorted).

- [ ] **Step 5: Run them to verify they pass**

Run: `uv run pytest -q -p no:cacheprovider tests/unit/lb_app/test_unification_service.py tests/unit/lb_app/test_experiment_to_analytics.py`
Expected: 12 passed

- [ ] **Step 6: Commit**

```bash
git add lb_app/services/unification_service.py lb_app/api.py tests/helpers/analytics_runs.py tests/unit/lb_app/test_unification_service.py tests/unit/lb_app/test_experiment_to_analytics.py
git commit -m "Add the unification service every UI uses"
```

---

### Task 3: TUI flow and the new `lb runs analyze`

**Files:**
- Create: `lb_ui/flows/unification.py`
- Modify: `lb_ui/cli/commands/runs.py` (replace the `analyze` command)
- Test: `tests/unit/lb_ui/test_unification_flow.py`; rewrite `tests/unit/lb_ui/test_cli_runs_analyze.py`

**Interfaces:**
- Consumes: everything Task 2 produces.
- Produces (in `lb_ui.flows.unification`):
  - `build_unification_service(cfg: BenchmarkConfig, root: Path | None = None, config_path: Path | None = None) -> UnificationService`
  - `is_interactive(ctx: UIContext) -> bool`
  - `run_unification_flow(ctx: UIContext, service: UnificationService, experiment: ExperimentInfo | None = None) -> list[Path] | None`
  - `show_summary(ctx: UIContext, preview: UnificationPreview) -> None`
  - `write_and_report(ctx: UIContext, service: UnificationService, preview: UnificationPreview) -> list[Path]`

- [ ] **Step 1: Write the failing flow tests** — `tests/unit/lb_ui/test_unification_flow.py`

```python
from collections.abc import Sequence
from pathlib import Path

import pandas as pd
import pytest

from lb_app.api import RunCatalogService, UnificationService
from lb_ui.flows.unification import run_unification_flow
from lb_ui.tui.system.headless import HeadlessUI
from lb_ui.tui.system.models import PickItem
from lb_ui.wiring.dependencies import UIContext
from tests.helpers.analytics_runs import collected_run

pytestmark = pytest.mark.unit_ui


class ScriptedPicker:
    """Answers pick_one/pick_many from scripted item ids, in order."""

    def __init__(self, ones: Sequence[str | None], manys: Sequence[list[str]] = ()):
        self.ones = list(ones)
        self.manys = list(manys)
        self.seen: list[list[str]] = []

    def pick_one(self, items, *, title, query_hint=""):
        self.seen.append([item.id for item in items])
        want = self.ones.pop(0)
        return next((item for item in items if item.id == want), None)

    def pick_many(self, items, *, title, query_hint=""):
        want = self.manys.pop(0)
        return [item for item in items if item.id in want]


def _ctx(picker: ScriptedPicker) -> tuple[UIContext, HeadlessUI]:
    ui = HeadlessUI()
    ui.picker = picker  # type: ignore[assignment]
    ctx = UIContext(headless=True)
    ctx.ui = ui
    return ctx, ui


@pytest.fixture
def service(tmp_path: Path) -> UnificationService:
    root = tmp_path / "tuning"  # a folder named like the experiment it holds
    collected_run(root, "run-1", "tuning", "fio", "2026-10-09T10:00:00")
    collected_run(root, "run-2", "tuning", "stress_ng", "2026-10-09T11:00:00")
    return UnificationService(RunCatalogService(root), tmp_path / "exports")


def test_pick_review_unify(service, tmp_path):
    picker = ScriptedPicker(["experiment:tuning", "unify"])
    ctx, ui = _ctx(picker)
    paths = run_unification_flow(ctx, service)
    assert paths
    assert picker.seen[0] == ["experiment:tuning", "folder:tuning"]
    assert (tmp_path / "exports" / "tuning" / "results.parquet").exists()
    titles = [t.model.title for t in ui.recorded_tables]
    assert titles[0] == "Unification of tuning"
    assert any("Equivalent command: lb runs analyze" in m for m in ui.recorded_messages)


def test_the_folder_entry_unifies_every_run(service, tmp_path):
    ctx, _ = _ctx(ScriptedPicker(["folder:tuning", "unify"]))
    run_unification_flow(ctx, service)
    runs = pd.read_parquet(tmp_path / "exports" / "tuning" / "runs.parquet")
    assert set(runs.run_id) == {"run-1", "run-2"}


def test_filters_then_unify(service, tmp_path):
    picker = ScriptedPicker(
        ["experiment:tuning", "filters", "unify"], manys=[["h1"], ["fio"]]
    )
    ctx, _ = _ctx(picker)
    run_unification_flow(ctx, service)
    results = pd.read_parquet(tmp_path / "exports" / "tuning" / "results.parquet")
    assert set(results.workload) == {"fio"}


def test_deselecting_everything_keeps_the_previous_filter(service, tmp_path):
    picker = ScriptedPicker(
        ["experiment:tuning", "filters", "filters", "unify"],
        manys=[["h1"], ["fio"], [], []],
    )
    ctx, _ = _ctx(picker)
    run_unification_flow(ctx, service)
    results = pd.read_parquet(tmp_path / "exports" / "tuning" / "results.parquet")
    assert set(results.workload) == {"fio"}


def test_cancel_writes_nothing(service, tmp_path):
    ctx, _ = _ctx(ScriptedPicker(["experiment:tuning", "cancel"]))
    assert run_unification_flow(ctx, service) is None
    assert not (tmp_path / "exports").exists()


def test_a_preselected_experiment_starts_at_the_summary(service, tmp_path):
    picker = ScriptedPicker(["unify"])
    ctx, _ = _ctx(picker)
    run_unification_flow(ctx, service, service.find("tuning"))
    assert picker.seen == [["unify", "filters", "cancel"]]


def test_an_empty_preview_offers_no_unify(service, monkeypatch):
    real_prepare = service.prepare
    monkeypatch.setattr(
        service,
        "prepare",
        lambda experiment, hosts=(), workloads=(): real_prepare(
            experiment, ["nobody"], workloads
        ),
    )
    picker = ScriptedPicker(["cancel"])
    ctx, _ = _ctx(picker)
    run_unification_flow(ctx, service, service.find("tuning"))
    assert picker.seen == [["filters", "cancel"]]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest -q -p no:cacheprovider tests/unit/lb_ui/test_unification_flow.py`
Expected: FAIL at collection: `ModuleNotFoundError: No module named 'lb_ui.flows.unification'`

- [ ] **Step 3: Implement** — `lb_ui/flows/unification.py`

```python
"""Pick an experiment, review what its unification produces, write it."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from rich.table import Table

from lb_app.api import (
    BenchmarkConfig,
    ExperimentInfo,
    RunCatalogService,
    UnificationError,
    UnificationPreview,
    UnificationService,
)
from lb_ui.tui.core.capabilities import is_tty_available
from lb_ui.tui.system.models import PickItem, TableModel
from lb_ui.wiring.dependencies import UIContext


def build_unification_service(
    cfg: BenchmarkConfig, root: Path | None = None, config_path: Path | None = None
) -> UnificationService:
    catalog = RunCatalogService(
        root or cfg.output_dir,
        report_dir=cfg.report_dir,
        data_export_dir=cfg.data_export_dir,
    )
    return UnificationService(catalog, cfg.data_export_dir, config_path=config_path)


def is_interactive(ctx: UIContext) -> bool:
    return not ctx.headless and is_tty_available()


def run_unification_flow(
    ctx: UIContext,
    service: UnificationService,
    experiment: ExperimentInfo | None = None,
) -> list[Path] | None:
    """Pick (unless preselected) → summary → unify, filter or cancel."""
    if experiment is None:
        experiment = _pick(ctx, service)
        if experiment is None:
            return None
    hosts: tuple[str, ...] = ()
    workloads: tuple[str, ...] = ()
    while True:
        with ctx.ui.progress.status(f"Loading {experiment.id}"):
            preview = service.prepare(experiment, hosts, workloads)
        show_summary(ctx, preview)
        actions = [] if preview.is_empty else [PickItem(id="unify", title="Unify")]
        actions += [
            PickItem(id="filters", title="Filters (hosts, workloads)"),
            PickItem(id="cancel", title="Cancel"),
        ]
        action = ctx.ui.picker.pick_one(actions, title=f"Unify {experiment.id}?")
        if action is None or action.id == "cancel":
            return None
        if action.id == "unify":
            return write_and_report(ctx, service, preview)
        hosts = _pick_subset(ctx, "hosts", experiment.hosts, preview.hosts)
        workloads = _pick_subset(
            ctx, "workloads", experiment.workloads, preview.workloads
        )


def show_summary(ctx: UIContext, preview: UnificationPreview) -> None:
    ctx.ui.tables.show(
        TableModel(
            title=f"Unification of {preview.experiment.id}",
            columns=["Field", "Value"],
            rows=[list(row) for row in preview.summary_rows()],
        )
    )


def write_and_report(
    ctx: UIContext, service: UnificationService, preview: UnificationPreview
) -> list[Path]:
    with ctx.ui.progress.status("Writing Parquet tables"):
        paths = service.write(preview)
    counts = preview.row_counts
    ctx.ui.tables.show(
        TableModel(
            title=f"Written to {preview.out_dir}",
            columns=["File", "Rows"],
            rows=[[p.name, str(counts.get(p.stem, "-"))] for p in paths],
        )
    )
    errors = preview.data.report.errors
    if errors:
        ctx.ui.present.warning(
            f"{len(errors)} load error(s): the data is partial, "
            "details in load_report.json"
        )
    ctx.ui.present.success(f"Unified {preview.experiment.id} into {preview.out_dir}")
    ctx.ui.present.info(f"Equivalent command: {preview.command}")
    return paths


def _pick(ctx: UIContext, service: UnificationService) -> ExperimentInfo | None:
    targets = service.list_targets()
    if not targets:
        raise UnificationError(f"No runs in {service.output_dir}")
    items = [_target_item(target) for target in targets]
    chosen = ctx.ui.picker.pick_one(items, title="Select what to unify")
    return chosen.payload if chosen else None


def _target_item(target: ExperimentInfo) -> PickItem:
    last = (
        target.last_created.strftime("%Y-%m-%d %H:%M") if target.last_created else "-"
    )
    title = f"Folder {target.id} (all runs)" if target.kind == "folder" else target.id
    return PickItem(
        id=f"{target.kind}:{target.id}",
        title=title,
        description=f"{len(target.runs)} run(s), last {last}",
        search_blob=" ".join([target.id, *target.hosts, *target.workloads]),
        preview=_runs_table(target),
        payload=target,
    )


def _runs_table(target: ExperimentInfo) -> Table:
    table = Table(title=target.id)
    for column in ("Run", "Created", "Hosts", "Workloads"):
        table.add_column(column)
    for run in target.runs:
        created = run.created_at.strftime("%Y-%m-%d %H:%M") if run.created_at else "-"
        table.add_row(
            run.run_id, created, ", ".join(run.hosts), ", ".join(run.workloads)
        )
    return table


def _pick_subset(
    ctx: UIContext,
    label: str,
    available: Sequence[str],
    current: tuple[str, ...],
) -> tuple[str, ...]:
    """Pick-many starting from the current filter; picking nothing keeps it."""
    items = [
        PickItem(id=name, title=name, selected=not current or name in current)
        for name in available
    ]
    chosen = ctx.ui.picker.pick_many(items, title=f"Select {label} to unify")
    return tuple(item.id for item in chosen) if chosen else current
```

- [ ] **Step 4: Run the flow tests to verify they pass**

Run: `uv run pytest -q -p no:cacheprovider tests/unit/lb_ui/test_unification_flow.py`
Expected: 7 passed

- [ ] **Step 5: Rewrite the CLI tests** — replace `tests/unit/lb_ui/test_cli_runs_analyze.py` with:

```python
"""CLI tests for lb runs analyze (experiment unification)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from lb_app.api import ConfigService
from lb_runner.api import BenchmarkConfig
from tests.helpers.analytics_runs import collected_run

pytestmark = [pytest.mark.unit_ui]


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import lb_ui.api as cli

    monkeypatch.setattr(
        cli.ctx_store, "config_service", ConfigService(config_home=tmp_path / "cfg")
    )
    root = tmp_path / "benchmark_results"
    collected_run(root, "run-1", "tuning", "fio", "2026-10-09T10:00:00")
    collected_run(root, "run-2", "tuning", "stress_ng", "2026-10-09T11:00:00")
    collected_run(root, "run-3", "other", "dd", "2026-10-09T09:00:00")
    config = tmp_path / "config.json"
    BenchmarkConfig(output_dir=root, data_export_dir=tmp_path / "exports").save(config)

    def invoke(*args: str):
        return CliRunner().invoke(
            cli.app, ["runs", "analyze", *args, "--config", str(config)]
        )

    return invoke, tmp_path / "exports"


def test_an_experiment_is_unified(setup):
    invoke, exports = setup
    result = invoke("--experiment", "tuning")
    assert result.exit_code == 0, result.output
    assert (exports / "tuning" / "results.parquet").exists()
    assert "Equivalent command" in result.output


def test_the_folder_is_unified(setup):
    invoke, exports = setup
    result = invoke("--folder")
    assert result.exit_code == 0, result.output
    assert (exports / "benchmark_results" / "runs.parquet").exists()


def test_experiment_and_folder_are_exclusive(setup):
    invoke, _ = setup
    result = invoke("--experiment", "tuning", "--folder")
    assert result.exit_code == 1
    assert "not both" in result.output


def test_without_a_terminal_a_target_is_required(setup):
    invoke, _ = setup
    result = invoke()
    assert result.exit_code == 1
    assert "--experiment ID or --folder" in result.output


def test_an_unknown_experiment_lists_recent_ones(setup):
    invoke, _ = setup
    result = invoke("--experiment", "nope")
    assert result.exit_code == 1
    assert "tuning" in result.output


def test_filters_that_leave_nothing_fail(setup):
    invoke, exports = setup
    result = invoke("--experiment", "tuning", "--host", "nobody")
    assert result.exit_code == 1
    assert "Nothing to unify" in result.output
    assert not (exports / "tuning").exists()


def test_load_errors_warn_but_still_write(setup, tmp_path):
    invoke, exports = setup
    broken = tmp_path / "benchmark_results" / "run-1" / "h1" / "fio" / "fio_plugin.csv"
    broken.write_text('"unterminated\n')
    result = invoke("--experiment", "tuning")
    assert result.exit_code == 0, result.output
    assert "load error" in result.output
    assert (exports / "tuning" / "results.parquet").exists()
```

- [ ] **Step 6: Run them to verify they fail**

Run: `uv run pytest -q -p no:cacheprovider tests/unit/lb_ui/test_cli_runs_analyze.py`
Expected: FAIL — `No such option: --experiment` (exit code 2) in most tests

- [ ] **Step 7: Replace the `analyze` command** in `lb_ui/cli/commands/runs.py`. Imports become:

```python
from lb_app.api import RunCatalogService, UnificationError
from lb_ui.flows.unification import (
    build_unification_service,
    is_interactive,
    run_unification_flow,
    show_summary,
    write_and_report,
)
```

and the command:

```python
@app.command("analyze")
def analyze(
    experiment: str | None = typer.Option(
        None, "--experiment", "-e", help="Experiment to unify."
    ),
    folder: bool = typer.Option(
        False,
        "--folder",
        help="Unify every run of the output folder as one experiment.",
    ),
    root: Path | None = typer.Option(
        None,
        "--root",
        "-r",
        help="Root directory containing benchmark_results run folders.",
    ),
    workload: list[str] | None = typer.Option(
        None,
        "--workload",
        "-w",
        help="Workload(s) to keep (repeatable). Default: all.",
    ),
    host: list[str] | None = typer.Option(
        None,
        "--host",
        "-H",
        help="Host(s) to keep (repeatable). Default: all.",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Config file to infer output/report/export roots.",
    ),
) -> None:
    """Unify an experiment's datasets into Parquet tables."""
    if experiment is not None and folder:
        ctx.ui.present.error("Use --experiment or --folder, not both.")
        raise typer.Exit(1)
    cfg, resolved, _ = ctx.config_service.load_for_read(config)
    service = build_unification_service(cfg, root, resolved)
    try:
        if experiment is None and not folder:
            if not is_interactive(ctx):
                ctx.ui.present.error(
                    "Choose what to unify: --experiment ID or --folder."
                )
                raise typer.Exit(1)
            run_unification_flow(ctx, service)
            return
        preview = service.prepare(service.find(experiment), host or (), workload or ())
        show_summary(ctx, preview)
        write_and_report(ctx, service, preview)
    except UnificationError as exc:
        ctx.ui.present.error(str(exc))
        raise typer.Exit(1) from exc
```

Also change the `create_runs_app` docstring to `"""Build the runs Typer app (list/show/analyze)."""`.

- [ ] **Step 8: Run the CLI and flow tests to verify they pass**

Run: `uv run pytest -q -p no:cacheprovider tests/unit/lb_ui/test_cli_runs_analyze.py tests/unit/lb_ui/test_unification_flow.py`
Expected: 14 passed

- [ ] **Step 9: Commit**

```bash
git add lb_ui/flows/unification.py lb_ui/cli/commands/runs.py tests/unit/lb_ui/test_unification_flow.py tests/unit/lb_ui/test_cli_runs_analyze.py
git commit -m "lb runs analyze unifies an experiment, with a TUI flow"
```

---

### Task 4: Lifecycle — `lb runs list` Analyze, `lb run --analyze` and the end-of-run prompt

**Files:**
- Modify: `lb_ui/flows/unification.py` (add `unify_after_run`), `lb_ui/cli/commands/runs.py` (Analyze action), `lb_ui/cli/commands/run.py` (`--analyze`)
- Test: `tests/unit/lb_ui/test_unification_lifecycle.py`

**Interfaces:**
- Consumes: Task 3's `build_unification_service`, `is_interactive`, `run_unification_flow`, `show_summary`, `write_and_report`.
- Produces: `unify_after_run(ctx: UIContext, cfg: BenchmarkConfig, journal_path: Path, config_path: Path | None, *, forced: bool) -> bool` — `False` only when a unification was attempted and failed.

- [ ] **Step 1: Write the failing tests** — `tests/unit/lb_ui/test_unification_lifecycle.py`

```python
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from lb_app.api import ConfigService
from lb_runner.api import BenchmarkConfig
from lb_ui.flows import unification
from lb_ui.tui.system.headless import HeadlessUI
from lb_ui.wiring.dependencies import UIContext
from tests.helpers.analytics_runs import collected_run

pytestmark = pytest.mark.unit_ui


class ScriptedPicker:
    def __init__(self, ones: Sequence[str]):
        self.ones = list(ones)

    def pick_one(self, items, *, title, query_hint=""):
        want = self.ones.pop(0)
        return next((item for item in items if item.id == want), None)

    def pick_many(self, items, *, title, query_hint=""):
        return []


@pytest.fixture
def cfg(tmp_path: Path) -> BenchmarkConfig:
    root = tmp_path / "benchmark_results"
    collected_run(root, "run-1", "tuning", "fio", "2026-10-09T10:00:00")
    collected_run(root, "run-2", "tuning", "stress_ng", "2026-10-09T11:00:00")
    return BenchmarkConfig(output_dir=root, data_export_dir=tmp_path / "exports")


def _ctx(headless: bool, confirm: bool = False) -> UIContext:
    ui = HeadlessUI()
    ui.next_confirm_response = confirm
    ctx = UIContext(headless=headless)
    ctx.ui = ui
    return ctx


def _journal(cfg: BenchmarkConfig) -> Path:
    return cfg.output_dir / "run-2" / "run_journal.json"


def test_forced_unifies_the_whole_experiment(cfg, tmp_path):
    assert unification.unify_after_run(
        _ctx(headless=True), cfg, _journal(cfg), None, forced=True
    )
    import pandas as pd

    runs = pd.read_parquet(tmp_path / "exports" / "tuning" / "runs.parquet")
    assert set(runs.run_id) == {"run-1", "run-2"}


def test_headless_without_analyze_does_nothing(cfg, tmp_path):
    assert unification.unify_after_run(
        _ctx(headless=True), cfg, _journal(cfg), None, forced=False
    )
    assert not (tmp_path / "exports").exists()


def test_the_prompt_defaults_to_no(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(unification, "is_tty_available", lambda: True)
    asked: list[bool] = []
    ctx = _ctx(headless=False)
    ctx.ui.form.confirm = lambda prompt, default=True: asked.append(default) or False
    unification.unify_after_run(ctx, cfg, _journal(cfg), None, forced=False)
    assert asked == [False]
    assert not (tmp_path / "exports").exists()


def test_yes_to_the_prompt_unifies(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(unification, "is_tty_available", lambda: True)
    ctx = _ctx(headless=False, confirm=True)
    assert unification.unify_after_run(ctx, cfg, _journal(cfg), None, forced=False)
    assert (tmp_path / "exports" / "tuning" / "results.parquet").exists()


def test_a_failed_forced_unification_reports_false(cfg, monkeypatch):
    monkeypatch.setattr(
        "lb_app.services.unification_service._has_pyarrow", lambda: False
    )
    ctx = _ctx(headless=True)
    assert not unification.unify_after_run(ctx, cfg, _journal(cfg), None, forced=True)
    assert any("pyarrow" in m for m in ctx.ui.recorded_messages)


def test_a_journal_without_experiment_warns_and_skips(cfg, tmp_path):
    journal = tmp_path / "old" / "run_journal.json"
    journal.parent.mkdir()
    journal.write_text('{"run_id": "old", "metadata": {}, "tasks": []}')
    ctx = _ctx(headless=True)
    assert unification.unify_after_run(ctx, cfg, journal, None, forced=True)
    assert any("no experiment id" in m for m in ctx.ui.recorded_messages)


def _load_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    import importlib
    import sys

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("LB_ENABLE_TEST_CLI", "1")
    monkeypatch.setenv("LB_SUPPRESS_SUMMARY", "1")
    monkeypatch.delenv("LB_CONFIG_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    for mod in list(sys.modules):
        if mod.startswith(("lb_ui.cli", "lb_ui.api")):
            del sys.modules[mod]
    return importlib.import_module("lb_ui.api")


@pytest.mark.parametrize(("flag", "forced"), [([], False), (["--analyze"], True)])
def test_lb_run_hands_the_journal_to_the_end_of_run_step(
    cfg, tmp_path, monkeypatch, flag, forced
):
    import sys

    cli = _load_cli(monkeypatch, tmp_path)
    cfg.workloads["stress_ng"] = cfg.workloads.get("stress_ng") or __import__(
        "lb_runner.api", fromlist=["WorkloadConfig"]
    ).WorkloadConfig(plugin="stress_ng", options={})
    cfg_path = tmp_path / "cfg.json"
    cfg.save(cfg_path)
    monkeypatch.setattr(
        cli.app_client,
        "_provision",
        lambda config, execution_mode, node_count, docker_engine=None, resume=None: (
            config,
            None,
        ),
    )
    journal = _journal(cfg)
    monkeypatch.setattr(
        cli.app_client,
        "start_run",
        lambda *_a, **_k: SimpleNamespace(
            journal_path=journal, log_path=None, ui_log_path=None
        ),
    )
    calls: list[tuple[Path, bool]] = []
    run_module = sys.modules["lb_ui.cli.commands.run"]
    monkeypatch.setattr(
        run_module,
        "unify_after_run",
        lambda ctx, cfg, path, config_path, *, forced: (
            calls.append((path, forced)) or not forced
        ),
    )
    result = CliRunner().invoke(cli.app, ["run", "-c", str(cfg_path), *flag])
    assert calls == [(journal, forced)]
    # --analyze with a failed unification exits 1; the prompt path never does.
    assert result.exit_code == (1 if forced else 0), result.output


def test_runs_list_analyze_starts_the_flow_at_the_summary(cfg, tmp_path, monkeypatch):
    import lb_ui.api as cli
    from lb_ui.tui.core import capabilities

    monkeypatch.setattr(
        cli.ctx_store, "config_service", ConfigService(config_home=tmp_path / "c")
    )
    monkeypatch.setattr(capabilities, "is_tty_available", lambda: True)
    ui = HeadlessUI()
    ui.picker = ScriptedPicker(["run-1", "analyze", "unify"])  # type: ignore[assignment]
    monkeypatch.setattr(cli.ctx_store, "ui", ui)
    monkeypatch.setattr(cli.ctx_store, "headless", False)
    cfg_path = tmp_path / "cfg.json"
    cfg.save(cfg_path)
    result = CliRunner().invoke(cli.app, ["runs", "list", "-c", str(cfg_path)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "exports" / "tuning" / "results.parquet").exists()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest -q -p no:cacheprovider tests/unit/lb_ui/test_unification_lifecycle.py`
Expected: FAIL — `AttributeError: module 'lb_ui.flows.unification' has no attribute 'unify_after_run'`; the `lb run` tests fail on `No such option: --analyze` / missing attribute; the runs-list test fails because no export is written.

- [ ] **Step 3: Implement `unify_after_run`** — append to `lb_ui/flows/unification.py` (add `RunJournal` to the `lb_app.api` import):

```python
def unify_after_run(
    ctx: UIContext,
    cfg: BenchmarkConfig,
    journal_path: Path,
    config_path: Path | None,
    *,
    forced: bool,
) -> bool:
    """End of ``lb run``: unify the run's experiment if asked to, or if agreed.

    Returns False only when a unification was attempted and failed.
    """
    if not forced and not is_interactive(ctx):
        return True
    experiment_id = (RunJournal.load(journal_path).metadata or {}).get("experiment_id")
    if not experiment_id:
        ctx.ui.present.warning(
            "The run's journal has no experiment id; nothing to unify."
        )
        return True
    if not forced and not ctx.ui.form.confirm(
        f"Unify experiment {experiment_id} now?", default=False
    ):
        return True
    service = build_unification_service(cfg, None, config_path)
    try:
        preview = service.prepare(service.find(experiment_id))
        show_summary(ctx, preview)
        write_and_report(ctx, service, preview)
    except UnificationError as exc:
        ctx.ui.present.error(str(exc))
        return False
    return True
```

- [ ] **Step 4: Wire `lb run`** — in `lb_ui/cli/commands/run.py` import `from lb_ui.flows.unification import unify_after_run`, add the option next to `--experiment`:

```python
analyze: bool = (
    typer.Option(
        False,
        "--analyze",
        help="Unify the run's experiment into Parquet tables when the run ends.",
    ),
)
```

and after `ctx.ui.present.success("Run completed.")`:

```python
if (
    result
    and result.journal_path
    and not unify_after_run(ctx, cfg, result.journal_path, resolved, forced=analyze)
    and analyze
):
    raise typer.Exit(1)
```

- [ ] **Step 5: Wire `lb runs list` → Analyze** — in `runs_list`, load with `cfg, resolved, _ = ctx.config_service.load_for_read(config)` and replace the `analyze` branch:

```python
        elif action.id == "analyze":
            run = catalog.get_run(selected.id)
            if run is None:
                return
            service = build_unification_service(cfg, output_root, resolved)
            try:
                run_unification_flow(
                    ctx, service, service.find(run.experiment_id or run.run_id)
                )
            except UnificationError as exc:
                ctx.ui.present.error(str(exc))
                raise typer.Exit(1) from exc
```

- [ ] **Step 6: Run them to verify they pass**

Run: `uv run pytest -q -p no:cacheprovider tests/unit/lb_ui/test_unification_lifecycle.py tests/unit/lb_ui/test_cli.py`
Expected: all passed

- [ ] **Step 7: Document** — in `docs/cli.md` and the root `CLI.md`, add `--analyze` to the `lb run` synopsis with the line "`--analyze`: when the run ends, unify its experiment into `data_exports/<experiment>/` without asking (interactive runs ask, default No)", and replace the `lb runs analyze` section with the new options (`--experiment/-e`, `--folder`, `--root/-r`, `--host/-H`, `--workload/-w`, `--config/-c`; no options in a terminal opens the picker).

- [ ] **Step 8: Commit**

```bash
git add lb_ui/flows/unification.py lb_ui/cli/commands/run.py lb_ui/cli/commands/runs.py tests/unit/lb_ui/test_unification_lifecycle.py docs/cli.md CLI.md
git commit -m "Unify from lb runs list, at the end of lb run, and with --analyze"
```

---

### Task 5: GUI parity

**Files:**
- Modify: `lb_gui/workers/analytics_worker.py` (runs any callable), `lb_gui/services/run_catalog.py` (`unification()`), `lb_gui/viewmodels/analytics_vm.py` (rewrite), `lb_gui/views/analytics_view.py` (rewrite), `lb_gui/windows/main_window.py` (constructor call), `lb_gui/app.py`, `lb_gui/services/__init__.py` (drop the analytics wrapper)
- Delete: `lb_gui/services/analytics_service.py`
- Test: rewrite `tests/unit/lb_gui/test_analytics_vm.py`; modify `tests/unit/lb_gui/test_workers_cleanup.py`, `tests/unit/lb_gui/test_services.py` (drop `TestAnalyticsServiceWrapper`); create `tests/unit/lb_gui/test_analytics_view.py`

**Interfaces:**
- Consumes: `UnificationService`, `UnificationPreview`, `ExperimentInfo` (Task 2).
- Produces:
  - `AnalyticsWorker(job: Callable[[], object], parent: QObject | None = None)`; `signals.finished: Signal(object)`, `signals.failed: Signal(str)`.
  - `RunCatalogServiceWrapper.unification() -> UnificationService`.
  - `AnalyticsViewModel(run_catalog, config_service=None, parent=None)` with signals `experiments_changed(list)`, `experiment_selected(object)`, `preview_changed(object)`, `analytics_started()`, `analytics_completed(list)`, `analytics_failed(str)`, `error_occurred(str)`; properties `experiments`, `selected_experiment`, `available_hosts`, `available_workloads`, `selected_hosts`/`selected_workloads` (setters clear the preview), `preview`, `last_artifacts`, `can_unify`; methods `refresh_runs()` (kept name: the main window calls it on every catalog VM), `configure`, `configure_with_config`, `select_experiment(index: int | None)`, `prepare()`, `unify()`, `get_experiment_rows() -> list[list[str]]`.

- [ ] **Step 1: Write the failing view-model tests** — replace `tests/unit/lb_gui/test_analytics_vm.py`:

```python
"""Unit tests for AnalyticsViewModel (experiment unification)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytest.importorskip("PySide6")

from lb_app.api import RunCatalogService, UnificationService  # noqa: E402
from tests.helpers.analytics_runs import collected_run  # noqa: E402

pytestmark = pytest.mark.unit


@pytest.fixture
def vm(tmp_path: Path):
    from lb_gui.viewmodels.analytics_vm import AnalyticsViewModel

    root = tmp_path / "benchmark_results"
    collected_run(root, "run-1", "tuning", "fio", "2026-10-09T10:00:00")
    collected_run(root, "run-2", "tuning", "stress_ng", "2026-10-09T11:00:00")
    catalog = MagicMock()
    catalog.unification.return_value = UnificationService(
        RunCatalogService(root), tmp_path / "exports"
    )
    model = AnalyticsViewModel(catalog)
    model.refresh_runs()
    return model


def test_the_folder_is_listed_first(vm):
    assert [(e.kind, e.id) for e in vm.experiments] == [
        ("folder", "benchmark_results"),
        ("experiment", "tuning"),
    ]
    assert vm.get_experiment_rows()[0][0] == "Folder benchmark_results (all runs)"


def test_selecting_defaults_the_filters_to_everything(vm):
    vm.select_experiment(1)
    assert vm.selected_experiment.id == "tuning"
    assert vm.selected_hosts == ["h1"]
    assert vm.selected_workloads == ["fio", "stress_ng"]
    assert vm.preview is None


def test_prepare_then_unify_writes(vm, tmp_path):
    completed: list[list[Path]] = []
    vm.analytics_completed.connect(completed.append)
    vm.select_experiment(1)
    vm.prepare()
    assert vm.preview is not None and vm.can_unify
    vm.unify()
    assert completed and (tmp_path / "exports" / "tuning" / "results.parquet").exists()


def test_changing_a_filter_drops_the_preview(vm):
    vm.select_experiment(1)
    vm.prepare()
    vm.selected_workloads = ["fio"]
    assert vm.preview is None
    assert not vm.can_unify


def test_an_empty_preview_cannot_be_unified(vm, tmp_path):
    failed: list[str] = []
    vm.analytics_failed.connect(failed.append)
    vm.select_experiment(1)
    vm.selected_hosts = ["nobody"]
    vm.prepare()
    assert vm.preview is not None and vm.preview.is_empty
    assert not vm.can_unify
    vm.unify()
    assert failed
    assert not (tmp_path / "exports").exists()


def test_prepare_without_selection_fails(vm):
    failed: list[str] = []
    vm.analytics_failed.connect(failed.append)
    vm.prepare()
    assert failed == ["No experiment selected"]
```

and the view construction test `tests/unit/lb_gui/test_analytics_view.py`:

```python
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.unit.lb_gui.test_analytics_vm import vm  # noqa: E402,F401

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def qt_app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_the_view_shows_experiments_and_the_summary(qt_app, vm):  # noqa: F811
    from lb_gui.views.analytics_view import AnalyticsView

    view = AnalyticsView(vm)
    assert view._experiment_table.rowCount() == 2
    vm.select_experiment(1)
    vm.prepare()
    assert view._summary_table.rowCount() == len(vm.preview.summary_rows())
    assert view._unify_btn.isEnabled()
    vm.unify()
    assert view._command_edit.text().startswith("lb runs analyze --experiment tuning")
```

In `tests/unit/lb_gui/test_workers_cleanup.py` change both `AnalyticsWorker(MagicMock(), MagicMock(), MagicMock())` to `AnalyticsWorker(MagicMock())`; in `tests/unit/lb_gui/test_services.py` delete the `TestAnalyticsServiceWrapper` class.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest -q -p no:cacheprovider tests/unit/lb_gui/test_analytics_vm.py tests/unit/lb_gui/test_analytics_view.py`
Expected: FAIL — `TypeError` on `AnalyticsViewModel(catalog)` (missing `run_catalog` argument) / no `experiments` attribute

- [ ] **Step 3: Worker** — `lb_gui/workers/analytics_worker.py` becomes:

```python
"""QThread worker that runs one analytics job (prepare or write)."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QThread, Signal


class AnalyticsWorkerSignals(QObject):
    """Signals emitted by AnalyticsWorker."""

    finished = Signal(object)  # the job's result
    failed = Signal(str)


class AnalyticsWorker(QObject):
    """Worker that runs a callable in a separate thread."""

    def __init__(
        self, job: Callable[[], object], parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._job = job
        self._thread: QThread | None = None
        self.signals = AnalyticsWorkerSignals()

    def start(self) -> None:
        """Start the worker in a new thread."""
        if self._thread is not None:
            return
        self._thread = QThread()
        self.moveToThread(self._thread)
        self._thread.started.connect(self._run)
        self._thread.finished.connect(self._clear_thread)
        self._thread.start()

    def _clear_thread(self) -> None:
        """Release the thread reference once the thread has fully stopped."""
        self._thread = None

    def _run(self) -> None:
        try:
            self.signals.finished.emit(self._job())
        except Exception as exc:
            self.signals.failed.emit(str(exc))
        finally:
            QThread.currentThread().quit()

    def is_running(self) -> bool:
        """Check if the worker is currently running."""
        return self._thread is not None
```

- [ ] **Step 4: Catalog wrapper** — in `lb_gui/services/run_catalog.py` import `UnificationService` from `lb_app.api`, set `self._export_root: Path | None = None` in `__init__`, `self._export_root = Path(config.data_export_dir)` in `configure`, and add:

```python
    def unification(self) -> UnificationService:
        """The unification service over the configured output folder."""
        service = self._ensure_configured()
        return UnificationService(service, self._export_root or service.output_dir)
```

- [ ] **Step 5: View-model** — replace `lb_gui/viewmodels/analytics_vm.py`:

```python
"""ViewModel for the Analytics view: experiment unification."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QCoreApplication, QObject, Signal

from lb_gui.utils import format_datetime
from lb_gui.workers import AnalyticsWorker

if TYPE_CHECKING:
    from lb_app.api import (
        BenchmarkConfig,
        ExperimentInfo,
        UnificationPreview,
        UnificationService,
    )
    from lb_gui.services import GUIConfigService, RunCatalogServiceWrapper


class AnalyticsViewModel(QObject):
    """State of the Analytics view; the work is UnificationService's."""

    experiments_changed = Signal(list)  # list[ExperimentInfo]
    experiment_selected = Signal(object)  # ExperimentInfo | None
    preview_changed = Signal(object)  # UnificationPreview | None
    analytics_started = Signal()
    analytics_completed = Signal(list)  # list[Path]
    analytics_failed = Signal(str)
    error_occurred = Signal(str)

    def __init__(
        self,
        run_catalog: RunCatalogServiceWrapper,
        config_service: GUIConfigService | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._run_catalog = run_catalog
        self._config_service = config_service
        self._experiments: list[ExperimentInfo] = []
        self._selected: ExperimentInfo | None = None
        self._selected_hosts: list[str] = []
        self._selected_workloads: list[str] = []
        self._preview: UnificationPreview | None = None
        self._last_artifacts: list[Path] = []
        self._worker: AnalyticsWorker | None = None
        self._pending: Callable[[object], None] | None = None
        self._is_configured: bool = config_service is None

    @property
    def experiments(self) -> list[ExperimentInfo]:
        return self._experiments

    @property
    def selected_experiment(self) -> ExperimentInfo | None:
        return self._selected

    @property
    def available_hosts(self) -> list[str]:
        return self._selected.hosts if self._selected else []

    @property
    def available_workloads(self) -> list[str]:
        return self._selected.workloads if self._selected else []

    @property
    def selected_hosts(self) -> list[str]:
        return self._selected_hosts

    @selected_hosts.setter
    def selected_hosts(self, value: list[str]) -> None:
        self._selected_hosts = value
        self._set_preview(None)

    @property
    def selected_workloads(self) -> list[str]:
        return self._selected_workloads

    @selected_workloads.setter
    def selected_workloads(self, value: list[str]) -> None:
        self._selected_workloads = value
        self._set_preview(None)

    @property
    def preview(self) -> UnificationPreview | None:
        return self._preview

    @property
    def can_unify(self) -> bool:
        return self._preview is not None and not self._preview.is_empty

    @property
    def last_artifacts(self) -> list[Path]:
        return self._last_artifacts

    def refresh_runs(self) -> None:
        """Reload the experiments list (folder entry first)."""
        if not self._is_configured and not self.configure():
            return
        try:
            targets = self._run_catalog.unification().list_targets()
        except Exception as exc:
            self.error_occurred.emit(f"Failed to list experiments: {exc}")
            targets = []
            self._is_configured = False
        folder = [t for t in targets if t.kind == "folder"]
        self._experiments = folder + [t for t in targets if t.kind != "folder"]
        self.experiments_changed.emit(self._experiments)

    def configure(self, config_path: Path | None = None) -> bool:
        """Configure the run catalog service using the benchmark config."""
        if self._config_service is None:
            self._is_configured = True
            return True
        if config_path is None:
            try:
                current = self._config_service.get_current_config()
                cached = current[0] if isinstance(current, tuple) and current else None
            except Exception:
                cached = None
            if cached is not None:
                self.configure_with_config(cached)
                return True
        try:
            config, _, _ = self._config_service.load_config(config_path)
            self._run_catalog.configure(config)
            self._is_configured = True
            return True
        except Exception as e:
            self.error_occurred.emit(f"Failed to load config: {e}")
            self._is_configured = False
            return False

    def configure_with_config(self, config: BenchmarkConfig) -> None:
        """Configure the run catalog service with a preloaded config."""
        self._run_catalog.configure(config)
        self._is_configured = True

    def select_experiment(self, index: int | None) -> None:
        """Select by row; the filters default to every host and workload."""
        valid = index is not None and 0 <= index < len(self._experiments)
        self._selected = (
            self._experiments[index] if valid and index is not None else None
        )
        self._selected_hosts = list(self.available_hosts)
        self._selected_workloads = list(self.available_workloads)
        self._set_preview(None)
        self.experiment_selected.emit(self._selected)

    def prepare(self) -> None:
        """Load the selection in the background and publish its preview."""
        experiment = self._selected
        if experiment is None:
            self.analytics_failed.emit("No experiment selected")
            return
        service = self._run_catalog.unification()
        hosts, workloads = list(self._selected_hosts), list(self._selected_workloads)
        self._start(
            lambda: service.prepare(experiment, hosts, workloads), self._on_prepared
        )

    def unify(self) -> None:
        """Write the prepared preview in the background."""
        preview = self._preview
        if preview is None or preview.is_empty:
            self.analytics_failed.emit("Prepare a non-empty unification first")
            return
        service = self._run_catalog.unification()
        self._start(lambda: service.write(preview), self._on_written)

    def get_experiment_rows(self) -> list[list[str]]:
        rows = []
        for target in self._experiments:
            name = (
                f"Folder {target.id} (all runs)"
                if target.kind == "folder"
                else target.id
            )
            rows.append(
                [
                    name,
                    str(len(target.runs)),
                    ", ".join(target.hosts),
                    ", ".join(target.workloads),
                    format_datetime(target.last_created),
                ]
            )
        return rows

    def _set_preview(self, preview: UnificationPreview | None) -> None:
        self._preview = preview
        self.preview_changed.emit(preview)

    def _on_prepared(self, preview: object) -> None:
        self._set_preview(preview)  # type: ignore[arg-type]

    def _on_written(self, paths: object) -> None:
        self._last_artifacts = list(paths)  # type: ignore[call-overload]
        self.analytics_completed.emit(self._last_artifacts)

    def _start(
        self, job: Callable[[], object], on_done: Callable[[object], None]
    ) -> None:
        if self._worker is not None and self._worker.is_running():
            return
        self.analytics_started.emit()
        if QCoreApplication.instance() is None or os.environ.get("PYTEST_CURRENT_TEST"):
            try:
                on_done(job())
            except Exception as exc:
                self.analytics_failed.emit(str(exc))
            return
        self._pending = on_done
        self._worker = AnalyticsWorker(job)
        # Bound methods of this QObject, so the slots run on the GUI thread.
        self._worker.signals.finished.connect(self._on_worker_finished)
        self._worker.signals.failed.connect(self._on_worker_failed)
        self._worker.start()

    def _on_worker_finished(self, result: object) -> None:
        self._worker = None
        if self._pending is not None:
            self._pending(result)

    def _on_worker_failed(self, error: str) -> None:
        self._worker = None
        self.analytics_failed.emit(error)
```

- [ ] **Step 6: View** — rewrite `lb_gui/views/analytics_view.py`, keeping its imports pattern, `_open_path` and the platform branches verbatim, and replacing the rest:

```python
class AnalyticsView(QWidget):
    """Pick an experiment, prepare its unification, write it."""

    EXPERIMENT_HEADERS: ClassVar[list[str]] = [
        "Experiment",
        "Runs",
        "Hosts",
        "Workloads",
        "Last run",
    ]

    def __init__(
        self, viewmodel: AnalyticsViewModel, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._vm = viewmodel
        self._setup_ui()
        self._connect_signals()
        self._vm.refresh_runs()
        self._on_experiments_changed(self._vm.experiments)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        title = QLabel("Analytics")
        set_widget_role(title, "title")
        layout.addWidget(title)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._vm.refresh_runs)
        left_layout.addWidget(refresh_btn)
        group = QGroupBox("Experiments")
        group_layout = QVBoxLayout(group)
        self._experiment_table = QTableWidget(0, len(self.EXPERIMENT_HEADERS))
        self._experiment_table.setHorizontalHeaderLabels(self.EXPERIMENT_HEADERS)
        self._experiment_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._experiment_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self._experiment_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._experiment_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._experiment_table.itemSelectionChanged.connect(self._on_row_changed)
        group_layout.addWidget(self._experiment_table)
        left_layout.addWidget(group, 1)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        runs_group = QGroupBox("Runs in the selection")
        runs_layout = QVBoxLayout(runs_group)
        self._runs_list = QListWidget()
        runs_layout.addWidget(self._runs_list)
        right_layout.addWidget(runs_group)

        filters = QGroupBox("Filters")
        filters_layout = QHBoxLayout(filters)
        self._hosts_list = self._filter_list(filters_layout, "Hosts:")
        self._workloads_list = self._filter_list(filters_layout, "Workloads:")
        self._hosts_list.itemSelectionChanged.connect(self._on_hosts_changed)
        self._workloads_list.itemSelectionChanged.connect(self._on_workloads_changed)
        right_layout.addWidget(filters)

        actions = QHBoxLayout()
        self._prepare_btn = QPushButton("Prepare")
        self._prepare_btn.clicked.connect(self._vm.prepare)
        self._unify_btn = QPushButton("Unify")
        self._unify_btn.clicked.connect(self._vm.unify)
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        for widget in (self._prepare_btn, self._unify_btn, self._progress):
            actions.addWidget(widget)
        right_layout.addLayout(actions)

        summary = QGroupBox("Summary")
        summary_layout = QVBoxLayout(summary)
        self._summary_table = QTableWidget(0, 2)
        self._summary_table.setHorizontalHeaderLabels(["Field", "Value"])
        self._summary_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._summary_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        summary_layout.addWidget(self._summary_table)
        right_layout.addWidget(summary, 1)

        result = QGroupBox("Result")
        result_layout = QVBoxLayout(result)
        self._artifacts_list = QListWidget()
        self._artifacts_list.itemDoubleClicked.connect(self._on_artifact_double_clicked)
        result_layout.addWidget(self._artifacts_list)
        command_row = QHBoxLayout()
        self._command_edit = QLineEdit()
        self._command_edit.setReadOnly(True)
        copy_btn = QPushButton("Copy")
        copy_btn.clicked.connect(
            lambda: QApplication.clipboard().setText(self._command_edit.text())
        )
        command_row.addWidget(self._command_edit)
        command_row.addWidget(copy_btn)
        result_layout.addLayout(command_row)
        right_layout.addWidget(result)

        splitter.addWidget(right)
        layout.addWidget(splitter, 1)
        self._status_label = QLabel("")
        layout.addWidget(self._status_label)
        self._sync_buttons()

    @staticmethod
    def _filter_list(parent: QHBoxLayout, label: str) -> QListWidget:
        column = QVBoxLayout()
        column.addWidget(QLabel(label))
        widget = QListWidget()
        widget.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        column.addWidget(widget)
        parent.addLayout(column)
        return widget

    def _connect_signals(self) -> None:
        self._vm.experiments_changed.connect(self._on_experiments_changed)
        self._vm.experiment_selected.connect(self._on_experiment_selected)
        self._vm.preview_changed.connect(self._on_preview_changed)
        self._vm.analytics_started.connect(self._on_started)
        self._vm.analytics_completed.connect(self._on_completed)
        self._vm.analytics_failed.connect(self._on_failed)
        self._vm.error_occurred.connect(self._on_error)

    def _on_row_changed(self) -> None:
        rows = self._experiment_table.selectionModel().selectedRows()
        self._vm.select_experiment(rows[0].row() if rows else None)

    def _on_hosts_changed(self) -> None:
        self._vm.selected_hosts = [i.text() for i in self._hosts_list.selectedItems()]

    def _on_workloads_changed(self) -> None:
        self._vm.selected_workloads = [
            i.text() for i in self._workloads_list.selectedItems()
        ]

    def _on_experiments_changed(self, experiments: list) -> None:
        rows = self._vm.get_experiment_rows()
        self._experiment_table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, cell in enumerate(row):
                self._experiment_table.setItem(i, j, QTableWidgetItem(cell))
        self._set_status(f"{len(experiments)} experiment(s) available", "muted")

    def _on_experiment_selected(self, experiment: ExperimentInfo | None) -> None:
        self._runs_list.clear()
        for widget, names in (
            (self._hosts_list, self._vm.available_hosts),
            (self._workloads_list, self._vm.available_workloads),
        ):
            widget.blockSignals(True)
            widget.clear()
            for name in names:
                item = QListWidgetItem(name)
                widget.addItem(item)
                item.setSelected(True)
            widget.blockSignals(False)
        if experiment is not None:
            for run in experiment.runs:
                self._runs_list.addItem(
                    f"{run.run_id}  {format_datetime(run.created_at)}  "
                    f"{', '.join(run.workloads)}"
                )
        self._sync_buttons()

    def _on_preview_changed(self, preview: UnificationPreview | None) -> None:
        rows = preview.summary_rows() if preview else []
        self._summary_table.setRowCount(len(rows))
        for i, (label, value) in enumerate(rows):
            self._summary_table.setItem(i, 0, QTableWidgetItem(label))
            self._summary_table.setItem(i, 1, QTableWidgetItem(value))
        self._progress.setVisible(False)
        self._sync_buttons()

    def _on_started(self) -> None:
        self._progress.setVisible(True)
        self._prepare_btn.setEnabled(False)
        self._unify_btn.setEnabled(False)
        self._set_status("Working...", "status-info")

    def _on_completed(self, paths: list) -> None:
        self._progress.setVisible(False)
        preview = self._vm.preview
        self._artifacts_list.clear()
        if preview is not None:
            self._artifacts_list.addItem(str(preview.out_dir))
            self._command_edit.setText(preview.command)
        for path in paths:
            self._artifacts_list.addItem(str(path))
        self._sync_buttons()
        self._set_status(f"Unified into {len(paths)} file(s)", "status-success")

    def _on_failed(self, error: str) -> None:
        self._progress.setVisible(False)
        self._sync_buttons()
        self._set_status(f"Failed: {error}", "status-error")

    def _on_error(self, message: str) -> None:
        self._set_status(message, "status-error")

    def _sync_buttons(self) -> None:
        self._prepare_btn.setEnabled(self._vm.selected_experiment is not None)
        self._unify_btn.setEnabled(self._vm.can_unify)

    def _set_status(self, text: str, role: str) -> None:
        self._status_label.setText(text)
        set_widget_role(self._status_label, role)

    def _on_artifact_double_clicked(self, item: QListWidgetItem) -> None:
        path = Path(item.text())
        if path.exists():
            self._open_path(path)
        else:
            QMessageBox.warning(
                self, "File Not Found", f"The file does not exist:\n{path}"
            )
```

followed by the unchanged `_open_path`. The import block gains `QApplication`, `QLineEdit` and drops `QComboBox`, `QFormLayout`; `TYPE_CHECKING` imports become `from lb_app.api import ExperimentInfo, UnificationPreview`; add `from lb_gui.utils import format_datetime, set_widget_role`. Keep whatever title role the old view used for `title` (read it before rewriting).

- [ ] **Step 7: Wiring** — in `lb_gui/windows/main_window.py` the view-model becomes `AnalyticsViewModel(self.services.run_catalog, self.services.config_service)`; delete `lb_gui/services/analytics_service.py`, its import and `__all__` entry in `lb_gui/services/__init__.py`, and the `analytics_service` property (and import) in `lb_gui/app.py`.

- [ ] **Step 8: Run the GUI tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen uv run pytest -q -p no:cacheprovider tests/unit/lb_gui tests/gui`
Expected: all passed

- [ ] **Step 9: Commit**

```bash
git add -A lb_gui tests/unit/lb_gui
git commit -m "GUI analytics view unifies experiments through the shared service"
```

---

### Task 6: Remove the per-run aggregate analytics

**Files:**
- Delete: `lb_analytics/engine/`, `lb_analytics/reporting/`, `lb_analytics/services/`, `lb_runner/metric_collectors/aggregators.py`, `tests/unit/lb_analytics/test_collectors.py`, `tests/unit/lb_analytics/test_data_handler.py`, `tests/unit/lb_analytics/test_data_handler_builtin.py`, `tests/unit/lb_runner/services_tests/test_aggregators.py`
- Modify: `lb_analytics/api.py`, `lb_app/api.py`, `lb_runner/api.py`, `lb_runner/metric_collectors/registry.py` (drop `aggregator`), `lb_runner/metric_collectors/builtin.py`, `lb_ui/wiring/dependencies.py` (drop `analytics_service`), `tests/unit/lb_runner/test_cli_collector.py` (drop the `aggregate_cli` tests), `lb_app/services/doctor_service.py` (pyarrow instead of matplotlib/seaborn), `pyproject.toml` + `uv.lock`, docs that mention the old command
- Test: `tests/unit/lb_app/test_aggregate_removed.py`

**Interfaces:**
- Consumes: nothing new; by now no product code calls the aggregate path (Tasks 3 and 5 replaced its callers).
- Produces: nothing.

- [ ] **Step 1: Write the failing test**

```python
import importlib

import pytest

pytestmark = pytest.mark.unit_analytics

GONE = {
    "lb_app.api": ["AnalyticsKind", "AnalyticsRequest", "AnalyticsService"],
    "lb_analytics.api": [
        "AnalyticsService",
        "DataHandler",
        "Reporter",
        "TestResult",
        "aggregate_cli",
        "aggregate_psutil",
    ],
    "lb_runner.api": ["aggregate_cli"],
}


@pytest.mark.parametrize("module", sorted(GONE))
def test_the_per_run_aggregate_analytics_is_gone(module):
    api = importlib.import_module(module)
    assert [name for name in GONE[module] if hasattr(api, name)] == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest -q -p no:cacheprovider tests/unit/lb_app/test_aggregate_removed.py`
Expected: 3 failed (each module still exports the names)

- [ ] **Step 3: Delete and unexport**
  - `git rm -r lb_analytics/engine lb_analytics/reporting lb_analytics/services lb_runner/metric_collectors/aggregators.py` and the four test files listed above.
  - `lb_analytics/api.py` keeps only `ExperimentData`, `LoadReport`, `load_experiment`.
  - `lb_app/api.py` drops the three `Analytics*` imports and `__all__` entries.
  - `lb_runner/api.py` drops `aggregate_cli`.
  - `registry.py`: delete the `aggregator` field; `builtin.py`: delete `PSUTIL_AGGREGATOR`, `CLI_AGGREGATOR` and the two `aggregator=` arguments.
  - `lb_ui/wiring/dependencies.py`: delete `_analytics_service`, the `analytics_service` property and setter, and the import.
  - `tests/unit/lb_runner/test_cli_collector.py`: delete the tests that call `aggregate_cli` and its import.
  - Fix any leftover reference: `rg -n "aggregate_cli|aggregate_psutil|DataHandler|Reporter\b|AnalyticsService|AnalyticsRequest|AnalyticsKind|\.aggregator\b" lb_* tests scripts docs` must print only prose about history, if anything.

- [ ] **Step 4: Dependencies** — remove `matplotlib` and `seaborn` from the `controller` extra and from the `dev` extra, remove `types-seaborn` from `[dependency-groups].dev`, run `uv lock`; in `lb_app/services/doctor_service.py` replace the two checks with `("pyarrow", self._check_import("pyarrow"), True),` and update any doctor test that lists the old names (`rg -n "matplotlib|seaborn" tests lb_*`).

- [ ] **Step 5: Docs** — `rg -n "runs analyze|aggregate|Reporter|DataHandler" docs README.md CLI.md` and rewrite each hit to the experiment flow (Task 4 already rewrote the `lb runs analyze` section in `docs/cli.md` and `CLI.md`); `docs/reference/analytics.md` gains a short "From the CLI, TUI and GUI" paragraph naming `lb runs analyze --experiment`, the picker, `lb run --analyze` and the GUI Analytics view.

- [ ] **Step 6: Run everything**

Run: `uv run pytest -q -p no:cacheprovider tests/unit/lb_app/test_aggregate_removed.py` → Expected: 3 passed
Run: `uv run pytest -q -p no:cacheprovider tests/unit` → Expected: all passed
Run: `uv run pre-commit run --all-files` → Expected: every hook Passed (deptry confirms no unused dependency is left)

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Remove the per-run aggregate analytics and its dependencies"
```
