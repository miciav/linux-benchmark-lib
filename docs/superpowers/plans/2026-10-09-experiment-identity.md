# Experiment Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every run records an `experiment_id` in its journal (from the config, `lb run --experiment`, or generated as `exp-%Y%m%d-%H%M%S`), and `RunCatalogService` groups runs into `ExperimentInfo` by id or by folder, ready for `load_experiment`.

**Architecture:** The id is a validated field on `BenchmarkConfig`; `lb run --experiment` overrides it through `RunRequest` → `RunService.create_session` → `RunContextBuilder`. `RunJournal.initialize()` → `_build_metadata()` records it (generating one when empty), keeps it out of the config hash, and resume rejects a different id. `RunInfo` gains `experiment_id`; the catalog adds `list_experiments`, `get_experiment`, `folder_experiment`.

**Tech Stack:** Python 3.12, pydantic v2, Typer, pytest.

**Spec:** `docs/superpowers/specs/2026-10-09-experiment-identity-design.md`

## Global Constraints

- Generated id format: `exp-%Y%m%d-%H%M%S`, UTC (same clock as `run-%Y%m%d-%H%M%S`).
- User id pattern: `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`.
- The id lives in `run_journal.json` as `metadata.experiment_id`; no separate registry.
- `experiment_id` is excluded from `config_hash`; `config_dump` still records it.
- Command line beats config file beats generation.
- Runs without an id (older journals) are one-run experiments named by `run_id`.
- Cross-package imports through `*.api` modules (ruff TID251, `scripts/check_api_imports.py`); `lb_ui` imports only `lb_app.api`.
- Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

- `lb run --experiment ""` (empty string): rejected by validation like any other invalid id, not silently treated as "generate one" — tested in Task 1.
- Resuming a run whose journal predates this change (no `metadata.experiment_id`) with a config that now sets one: the resume proceeds, no false "belongs to experiment" error — tested in Task 2.
- An id set both in the config file and with `--experiment`: the command line wins — tested in Task 3.
- An output folder with no runs: `list_experiments()` is empty and `folder_experiment()` has no runs, no exception — tested in Task 4.
- A folder mixing new runs (with ids) and older runs (without): older ones appear as one-run experiments named by `run_id`, never merged into a real experiment — tested in Task 4.

---

### Task 1: `experiment_id` on `BenchmarkConfig`

**Files:**
- Modify: `lb_runner/models/config.py` (field, validator, `validate_experiment_id`)
- Modify: `lb_runner/api.py` (export `validate_experiment_id`)
- Test: `tests/unit/lb_runner/test_experiment_id_config.py`

**Interfaces:**
- Produces: `BenchmarkConfig.experiment_id: str | None` (default `None`, validated); `validate_experiment_id(value: str | None) -> str | None` exported from `lb_runner.api` (raises `ValueError` on an invalid id, returns the value otherwise).

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/lb_runner/test_experiment_id_config.py
import pytest
from pydantic import ValidationError

from lb_runner.api import BenchmarkConfig, validate_experiment_id

pytestmark = pytest.mark.unit_runner


@pytest.mark.parametrize("value", ["tuning-io", "exp-20261009-151200", "a", "A.b_c-1"])
def test_valid_experiment_ids_are_accepted(value: str) -> None:
    assert BenchmarkConfig(experiment_id=value).experiment_id == value
    assert validate_experiment_id(value) == value


@pytest.mark.parametrize(
    "value", ["", "has space", "a/b", "..", "-leading", "x" * 65, "ünïcode"]
)
def test_invalid_experiment_ids_are_rejected(value: str) -> None:
    with pytest.raises(ValidationError, match="experiment"):
        BenchmarkConfig(experiment_id=value)
    with pytest.raises(ValueError, match="letters, digits"):
        validate_experiment_id(value)


def test_experiment_id_defaults_to_none() -> None:
    assert BenchmarkConfig().experiment_id is None
    assert validate_experiment_id(None) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest -q -p no:cacheprovider tests/unit/lb_runner/test_experiment_id_config.py`
Expected: FAIL with `ImportError: cannot import name 'validate_experiment_id'`.

- [ ] **Step 3: Implement**

In `lb_runner/models/config.py` (add `import re` and `field_validator` to the pydantic import if missing), above `class BenchmarkConfig`:

```python
# Also names a folder (data_exports/<experiment>/), hence the strict alphabet.
_EXPERIMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def validate_experiment_id(value: str | None) -> str | None:
    """Return ``value`` if it is a valid experiment id (or None), else raise."""
    if value is None or _EXPERIMENT_ID.fullmatch(value):
        return value
    raise ValueError(
        f"invalid experiment id {value!r}: use 1-64 letters, digits, '.', '_' "
        "or '-', starting with a letter or digit"
    )
```

Inside `BenchmarkConfig`, after `repetitions`:

```python
experiment_id: str | None = Field(
    default=None,
    description=(
        "Experiment this run belongs to; generated as exp-<date>-<time> "
        "when empty. lb run --experiment overrides it."
    ),
)


@field_validator("experiment_id")
@classmethod
def _check_experiment_id(cls, value: str | None) -> str | None:
    return validate_experiment_id(value)
```

In `lb_runner/api.py`, import `validate_experiment_id` from `lb_runner.models.config` and add it to `__all__` (sorted).

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest -q -p no:cacheprovider tests/unit/lb_runner/test_experiment_id_config.py`
Expected: PASS (13 tests).

- [ ] **Step 5: Commit**

```bash
uv run ruff check lb_runner tests/unit/lb_runner && uv run ruff format lb_runner tests/unit/lb_runner
git add lb_runner tests/unit/lb_runner/test_experiment_id_config.py
git commit -m "Add a validated experiment_id to BenchmarkConfig

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The journal records, generates and guards the id

**Files:**
- Modify: `lb_controller/services/paths.py` (`generate_experiment_id`)
- Modify: `lb_controller/services/journal.py` (`_build_metadata`, `_config_hash`, `_validate_config`, its call in `RunJournal.load`)
- Test: `tests/unit/lb_controller/test_journal_experiment_id.py`

**Interfaces:**
- Consumes: `BenchmarkConfig.experiment_id` (Task 1).
- Produces: `generate_experiment_id() -> str` in `lb_controller/services/paths.py`; `RunJournal.initialize(...).metadata["experiment_id"]` always a non-empty string.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/lb_controller/test_journal_experiment_id.py
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest -q -p no:cacheprovider tests/unit/lb_controller/test_journal_experiment_id.py`
Expected: FAIL with `ImportError: cannot import name 'generate_experiment_id'`.

- [ ] **Step 3: Implement**

`lb_controller/services/paths.py`, next to `generate_run_id`:

```python
def generate_experiment_id() -> str:
    """Generate an experiment id; same clock as run ids, its own namespace."""
    return datetime.now(UTC).strftime("exp-%Y%m%d-%H%M%S")
```

`lb_controller/services/journal.py`:

```python
from lb_controller.services.paths import generate_experiment_id
```

```python
def _config_hash(cfg_dump: dict[str, Any]) -> str:
    """Stable hash for config dumps.

    The experiment id is a label, not an execution parameter: hashing it would
    make a run with a generated id impossible to resume with its own config.
    """
    hashed = {k: v for k, v in cfg_dump.items() if k != "experiment_id"}
    try:
        payload = json.dumps(hashed, sort_keys=True, default=str).encode("utf-8")
    except Exception:
        payload = str(hashed).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
```

In `_build_metadata`, add the key:

```python
        "experiment_id": getattr(config, "experiment_id", None)
        or generate_experiment_id(),
```

`_validate_config` gains the run id and the experiment check (keep the existing body after it):

```python
def _validate_config(
    metadata: dict[str, Any], config: Any | None, run_id: str | None = None
) -> None:
    if config is None:
        return
    requested = getattr(config, "experiment_id", None)
    recorded = metadata.get("experiment_id")
    if requested and recorded and requested != recorded:
        raise ValueError(
            f"{run_id or 'This run'} belongs to experiment {recorded!r}, not "
            f"{requested!r}; aborting resume."
        )
    ...  # existing repetitions / config hash checks unchanged
```

and in `RunJournal.load`: `_validate_config(metadata, config, data.get("run_id"))`.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest -q -p no:cacheprovider tests/unit/lb_controller/test_journal_experiment_id.py tests/unit/lb_controller`
Expected: PASS (7 new tests plus the existing controller suite).

- [ ] **Step 5: Commit**

```bash
uv run ruff check lb_controller tests/unit/lb_controller && uv run ruff format lb_controller tests/unit/lb_controller
git add lb_controller tests/unit/lb_controller/test_journal_experiment_id.py
git commit -m "Record, generate and guard the experiment id in the run journal

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `lb run --experiment` and the end-of-run hint

**Files:**
- Modify: `lb_app/interfaces.py` (`RunRequest.experiment_id`)
- Modify: `lb_app/client.py` (pass it to `create_session`)
- Modify: `lb_app/services/run_service.py` (`create_session` parameter, forwarded)
- Modify: `lb_app/services/run_context_builder.py` (`create_session` parameter, `_apply_experiment`)
- Modify: `lb_ui/cli/commands/run.py` (`--experiment` option, into `RunRequest`)
- Modify: `lb_ui/cli/commands/run_helpers.py` (`print_run_journal_summary` prints the experiment)
- Modify: `docs/cli.md`
- Test: `tests/unit/lb_app/test_run_experiment_override.py`, `tests/unit/lb_ui/test_run_experiment_hint.py`

**Interfaces:**
- Consumes: `validate_experiment_id` (Task 1, `lb_runner.api`); journal `metadata["experiment_id"]` (Task 2).
- Produces: `RunRequest.experiment_id: str | None = None`; `RunContextBuilder.create_session(..., experiment_id: str | None = None)` and the same keyword on `RunService.create_session`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/lb_app/test_run_experiment_override.py
import pytest

from lb_app.services.run_context_builder import RunContextBuilder
from lb_runner.api import BenchmarkConfig

pytestmark = pytest.mark.unit_ui


def test_command_line_beats_the_config_file() -> None:
    cfg = BenchmarkConfig(experiment_id="from-config")
    RunContextBuilder._apply_experiment(cfg, "from-cli")
    assert cfg.experiment_id == "from-cli"


def test_no_command_line_keeps_the_config_value() -> None:
    cfg = BenchmarkConfig(experiment_id="from-config")
    RunContextBuilder._apply_experiment(cfg, None)
    assert cfg.experiment_id == "from-config"


@pytest.mark.parametrize("bad", ["", "a b", "../x"])
def test_an_invalid_command_line_id_fails_before_the_run(bad: str) -> None:
    with pytest.raises(ValueError, match="letters, digits"):
        RunContextBuilder._apply_experiment(BenchmarkConfig(), bad)
```

```python
# tests/unit/lb_ui/test_run_experiment_hint.py
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest -q -p no:cacheprovider tests/unit/lb_app/test_run_experiment_override.py tests/unit/lb_ui/test_run_experiment_hint.py`
Expected: FAIL — `RunContextBuilder` has no attribute `_apply_experiment`, and the summary has no experiment line.

- [ ] **Step 3: Implement**

`lb_app/interfaces.py`, in `RunRequest` after `repetitions`:

```python
    experiment_id: str | None = None
```

`lb_app/services/run_context_builder.py`: add `experiment_id: str | None = None` to `create_session` (after `repetitions`), and call `self._apply_experiment(cfg, experiment_id)` right after `self._apply_setup_overrides(...)`. Add:

```python
    @staticmethod
    def _apply_experiment(cfg: BenchmarkConfig, experiment_id: str | None) -> None:
        """--experiment wins over the config file; validated before any run."""
        if experiment_id is None:
            return
        cfg.experiment_id = validate_experiment_id(experiment_id)
```

with `from lb_runner.api import validate_experiment_id` (use the module's existing `lb_runner.api` import line).

`lb_app/services/run_service.py`: add `experiment_id: str | None = None` to `create_session` after `repetitions` and forward `experiment_id=experiment_id` to the builder call.

`lb_app/client.py`: in the `create_session(...)` call, add `experiment_id=request.experiment_id,` after `repetitions=request.repetitions,`.

`lb_ui/cli/commands/run.py`: add the option after `run_id`:

```python
experiment: str | None = (
    typer.Option(
        None,
        "--experiment",
        "-e",
        help=(
            "Experiment to add this run to; a new exp-<date>-<time> id is "
            "generated when omitted."
        ),
    ),
)
```

and `experiment_id=experiment,` in `RunRequest(...)`.

`lb_ui/cli/commands/run_helpers.py`, in `print_run_journal_summary`, right after `ctx.ui.tables.show(build_journal_table(journal))`:

```python
    experiment_id = (journal.metadata or {}).get("experiment_id")
    if experiment_id:
        ctx.ui.present.info(
            f"Experiment: {experiment_id} — to add runs to it: "
            f"lb run --experiment {experiment_id}"
        )
```

`docs/cli.md`, in the `lb run` entry, document `--experiment/-e NAME` with the generation rule and the allowed characters.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest -q -p no:cacheprovider tests/unit/lb_app tests/unit/lb_ui`
Expected: PASS (new tests plus the existing app and UI suites).

- [ ] **Step 5: Commit**

```bash
uv run ruff check lb_app lb_ui tests/unit/lb_app tests/unit/lb_ui && uv run ruff format lb_app lb_ui tests/unit/lb_app tests/unit/lb_ui
git add lb_app lb_ui docs/cli.md tests/unit/lb_app/test_run_experiment_override.py tests/unit/lb_ui/test_run_experiment_hint.py
git commit -m "Add lb run --experiment and print the experiment after a run

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: `ExperimentInfo` and the experiment catalog

**Files:**
- Modify: `lb_common/models/run_info.py` (`RunInfo.experiment_id`, new `ExperimentInfo`)
- Modify: `lb_common/api.py` (export `ExperimentInfo`)
- Modify: `lb_controller/services/run_catalog_service.py` (read the id; `list_experiments`, `get_experiment`, `folder_experiment`)
- Modify: `lb_app/api.py` (re-export `ExperimentInfo`)
- Test: `tests/unit/lb_controller/test_experiment_catalog.py`

**Interfaces:**
- Consumes: journal `metadata["experiment_id"]` (Task 2).
- Produces: `RunInfo.experiment_id: str | None = None` (last field, defaulted); `ExperimentInfo(id: str, kind: Literal["experiment", "folder"], runs: Sequence[RunInfo])` with properties `hosts: list[str]`, `workloads: list[str]`, `first_created: datetime | None`, `last_created: datetime | None`; `RunCatalogService.list_experiments() -> list[ExperimentInfo]`, `get_experiment(experiment_id: str) -> ExperimentInfo | None`, `folder_experiment() -> ExperimentInfo`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/lb_controller/test_experiment_catalog.py
import json
from pathlib import Path

import pytest

from lb_controller.api import RunCatalogService

pytestmark = pytest.mark.unit_controller


def _run(
    root: Path, run_id: str, created: str, experiment: str | None, host: str
) -> None:
    run_dir = root / run_id
    run_dir.mkdir(parents=True)
    metadata = {"created_at": created}
    if experiment is not None:
        metadata["experiment_id"] = experiment
    tasks = [{"host": host, "workload": "fio"}]
    (run_dir / "run_journal.json").write_text(
        json.dumps({"run_id": run_id, "metadata": metadata, "tasks": tasks})
    )


@pytest.fixture
def catalog(tmp_path: Path) -> RunCatalogService:
    root = tmp_path / "benchmark_results"
    _run(root, "run-a1", "2026-10-09T10:00:00", "tuning", "h1")
    _run(root, "run-a2", "2026-10-09T12:00:00", "tuning", "h2")
    _run(root, "run-b1", "2026-10-09T11:00:00", "other", "h1")
    _run(root, "run-old", "2026-10-01T09:00:00", None, "h1")  # before this change
    return RunCatalogService(root)


def test_runs_expose_their_experiment(catalog: RunCatalogService) -> None:
    run = catalog.get_run("run-a1")
    assert run is not None and run.experiment_id == "tuning"


def test_runs_group_by_experiment_newest_first(catalog: RunCatalogService) -> None:
    experiments = catalog.list_experiments()
    assert [e.id for e in experiments] == ["tuning", "other", "run-old"]
    tuning = experiments[0]
    assert tuning.kind == "experiment"
    assert [r.run_id for r in tuning.runs] == ["run-a1", "run-a2"]
    assert tuning.hosts == ["h1", "h2"]
    assert tuning.workloads == ["fio"]
    assert str(tuning.first_created) == "2026-10-09 10:00:00"
    assert str(tuning.last_created) == "2026-10-09 12:00:00"


def test_older_runs_stay_one_run_experiments(catalog: RunCatalogService) -> None:
    old = catalog.get_experiment("run-old")
    assert old is not None and [r.run_id for r in old.runs] == ["run-old"]


def test_get_experiment_unknown_is_none(catalog: RunCatalogService) -> None:
    assert catalog.get_experiment("nope") is None


def test_folder_experiment_holds_every_run(catalog: RunCatalogService) -> None:
    folder = catalog.folder_experiment()
    assert folder.kind == "folder"
    assert folder.id == "benchmark_results"
    assert len(folder.runs) == 4


def test_an_empty_folder_has_no_experiments(tmp_path: Path) -> None:
    empty = RunCatalogService(tmp_path / "nothing-here")
    assert empty.list_experiments() == []
    assert empty.folder_experiment().runs == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest -q -p no:cacheprovider tests/unit/lb_controller/test_experiment_catalog.py`
Expected: FAIL with `AttributeError: 'RunInfo' object has no attribute 'experiment_id'`.

- [ ] **Step 3: Implement**

`lb_common/models/run_info.py`: add `from typing import Literal`; append to `RunInfo`:

```python
    experiment_id: str | None = None
```

and add below it:

```python
@dataclass(frozen=True)
class ExperimentInfo:
    """A group of runs: same experiment_id, or every run of one folder."""

    id: str
    kind: Literal["experiment", "folder"]
    runs: Sequence[RunInfo]

    @property
    def hosts(self) -> list[str]:
        return sorted({host for run in self.runs for host in run.hosts})

    @property
    def workloads(self) -> list[str]:
        return sorted({w for run in self.runs for w in run.workloads})

    @property
    def first_created(self) -> datetime | None:
        stamps = [run.created_at for run in self.runs if run.created_at]
        return min(stamps) if stamps else None

    @property
    def last_created(self) -> datetime | None:
        stamps = [run.created_at for run in self.runs if run.created_at]
        return max(stamps) if stamps else None
```

Export `ExperimentInfo` from `lb_common/api.py` (sorted `__all__`) and re-export it from `lb_app/api.py` next to `RunInfo`.

`lb_controller/services/run_catalog_service.py`: in `get_run`, pass `experiment_id=_experiment_of(journal_data)` to `RunInfo(...)`; add methods to `RunCatalogService`:

```python
def list_experiments(self) -> list[ExperimentInfo]:
    """Group the folder's runs by experiment, newest experiment first.

    Runs without an id (journals older than experiment ids) are one-run
    experiments named after their run_id.
    """
    groups: dict[str, list[RunInfo]] = {}
    for run in self.list_runs():
        groups.setdefault(run.experiment_id or run.run_id, []).append(run)
    experiments = [
        ExperimentInfo(id=key, kind="experiment", runs=_oldest_first(runs))
        for key, runs in groups.items()
    ]
    return sorted(experiments, key=lambda e: _stamp(e.last_created), reverse=True)


def get_experiment(self, experiment_id: str) -> ExperimentInfo | None:
    return next((e for e in self.list_experiments() if e.id == experiment_id), None)


def folder_experiment(self) -> ExperimentInfo:
    """Every run of the folder as one experiment named after the folder."""
    return ExperimentInfo(
        id=self.output_dir.name,
        kind="folder",
        runs=_oldest_first(self.list_runs()),
    )
```

and module-level helpers:

```python
def _experiment_of(journal_data: dict[str, Any]) -> str | None:
    value = journal_data.get("metadata", {}).get("experiment_id")
    return value if isinstance(value, str) and value else None


def _stamp(created: datetime | None) -> float:
    return created.timestamp() if created else 0.0


def _oldest_first(runs: list[RunInfo]) -> list[RunInfo]:
    return sorted(runs, key=lambda run: _stamp(run.created_at))
```

with `from lb_common.api import ExperimentInfo, RunInfo`.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest -q -p no:cacheprovider tests/unit/lb_controller tests/unit/lb_common tests/unit/lb_app`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff check lb_common lb_controller lb_app tests/unit/lb_controller && uv run ruff format lb_common lb_controller lb_app tests/unit/lb_controller
git add lb_common lb_controller lb_app/api.py tests/unit/lb_controller/test_experiment_catalog.py
git commit -m "Group runs into experiments in the run catalog

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: From an experiment to unified tables

**Files:**
- Test: `tests/unit/lb_app/test_experiment_to_analytics.py`
- Modify: `docs/reference/analytics.md`

**Interfaces:**
- Consumes: `RunCatalogService.get_experiment` (Task 4); `load_experiment` (sub-project A); `write_host_manifest`, `write_workload_manifest` (`lb_runner.api`).

- [ ] **Step 1: Write the test**

```python
# tests/unit/lb_app/test_experiment_to_analytics.py
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
        "metadata": {"created_at": "2026-10-09T10:00:00", "experiment_id": experiment},
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
```

- [ ] **Step 2: Run it**

Run: `uv run pytest -q -p no:cacheprovider tests/unit/lb_app/test_experiment_to_analytics.py`
Expected: PASS. This task adds no production code: it pins the link between the catalog (Task 4) and `load_experiment`. To prove the test can fail, temporarily change `"tuning"` in `get_experiment("tuning")` to `"other"`, see the assertions fail, and restore it.

- [ ] **Step 3: Document**

Append to the "Unified datasets" section of `docs/reference/analytics.md`:

```markdown
Runs are grouped into experiments by `RunCatalogService`: `list_experiments()`,
`get_experiment(id)` and `folder_experiment()` return `ExperimentInfo` objects
whose `runs` feed `load_experiment` directly:

    experiment = RunCatalogService(output_dir).get_experiment("exp-20261009-151200")
    data = load_experiment(experiment.runs)
```

- [ ] **Step 4: Full suite and hooks**

Run: `uv run pytest -q -p no:cacheprovider tests/unit && uv run pre-commit run --all-files`
Expected: both exit 0.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/lb_app/test_experiment_to_analytics.py docs/reference/analytics.md
git commit -m "Pin the experiment-to-analytics link and document it

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
