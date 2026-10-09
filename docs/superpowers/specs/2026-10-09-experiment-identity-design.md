# Analytics: experiment identity — design

Date: 2026-10-09
Status: approved in conversation, pending written review
Scope: sub-project **B** of the analytics work. A (dataset unification,
`docs/superpowers/specs/2026-10-09-analytics-dataset-unification-design.md`)
is merged; C (CLI/TUI/GUI wiring) builds on this one.

## Goal

Group runs into experiments, so that the unification of sub-project A can be
fed "every run of this experiment" instead of a hand-picked list. An experiment
is either the set of runs sharing an `experiment_id`, or every run in an output
folder.

## Decisions

| Topic | Decision |
|---|---|
| Where the id comes from | `experiment_id` field in `BenchmarkConfig` (config files can pin it) and `lb run --experiment NAME`; the command line wins. |
| No id given | Generated as `exp-%Y%m%d-%H%M%S` (UTC), the same clock and shape as `run-%Y%m%d-%H%M%S`, in its own namespace so it is never mistaken for a run id. |
| Where it lives | In each run's `run_journal.json`, as `metadata.experiment_id`. No separate experiment registry: an experiment is the set of runs whose journals carry the same id. |
| Grouping by folder | Every run in one output folder forms one experiment of kind `folder`, named after the folder. |
| Runs from before this change | No id in their journal: each is a one-run experiment named after its `run_id`. |

## Lifecycle of the id

| Step | What happens | Where |
|---|---|---|
| Declaration | `BenchmarkConfig.experiment_id: str \| None`; `lb run --experiment` sets `RunRequest.experiment_id`, which overrides the config value before the run starts | `lb_runner` (model), `lb_app` (`RunRequest`), `lb_ui` (option) |
| Generation | `RunJournal.initialize()` is the single place every journal is born (new runs, rebuilt journals). Its `_build_metadata(config)` records `config.experiment_id` or, when empty, `generate_experiment_id()` | `lb_controller/services/journal.py`, `generate_experiment_id()` next to `generate_run_id()` in `lb_controller/services/paths.py` |
| Recording | `metadata.experiment_id` in `run_journal.json` — already read by `load_experiment` into the `runs` table | `lb_controller` |
| Resume | The journal's id stands. A resume that asks for a different `experiment_id` fails with "run X belongs to experiment Y" | `_validate_config` in `lb_controller/services/journal.py` |
| Reporting | At the end of `lb run`: `Experiment: exp-… — to add runs to it: lb run --experiment exp-…` | `lb_ui` |

Rules:

1. **Validation.** A user-given id matches `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`:
   letters, digits, `.`, `_`, `-`, at most 64 characters, alphanumeric first.
   It also names a folder (`data_exports/<experiment>/` in C), so spaces, `/`
   and `..` are rejected with a message stating the allowed characters. The
   check is a pydantic validator on `BenchmarkConfig`, so it covers both the
   config file and the command line, and it fails before anything runs.
2. **The id is not part of the config hash.** Resume compares a hash of the
   configuration; the id is a label, not an execution parameter. If it were
   hashed, a run whose id was generated could not be resumed with its original
   config file, which carries no id. `_config_hash` drops `experiment_id`
   before hashing; `config_dump` still records it.

## Catalog

`RunCatalogService` (`lb_controller/services/run_catalog_service.py`) is
extended; no new service.

| Element | Addition |
|---|---|
| `RunInfo.experiment_id: str \| None` (`lb_common`) | Read from the journal's `metadata.experiment_id`; `None` when absent or unreadable. |
| `ExperimentInfo` (new, `lb_common`, next to `RunInfo`) | `id: str`, `kind: Literal["experiment", "folder"]`, `runs: list[RunInfo]`; properties `hosts`, `workloads` (sorted unions), `first_created`, `last_created` (from the runs' `created_at`) for the TUI preview. |
| `RunCatalogService.list_experiments()` | Groups the folder's runs by `experiment_id` (runs without one become one-run experiments named by `run_id`); newest first by `last_created`; runs inside an experiment oldest first. |
| `RunCatalogService.get_experiment(experiment_id)` | The matching `ExperimentInfo`, or `None`. |
| `RunCatalogService.folder_experiment()` | Every run of the folder as one `ExperimentInfo` of kind `folder`, id = the folder name. |

`ExperimentInfo` reaches CLI, TUI and GUI through `lb_app.api`, alongside
`RunInfo`. Feeding sub-project A is one line:

```python
experiment = catalog.get_experiment("exp-20261009-151200")
data = load_experiment(experiment.runs)
```

Known limit: a catalog sees one output folder, as today. An experiment whose
runs were written to different output folders appears split, one part per
folder. Merging folders is left out until it is needed.

## Error handling

| Situation | Behaviour |
|---|---|
| Invalid `--experiment` or config `experiment_id` | Validation error before anything starts, naming the allowed characters; no run is created |
| `lb resume` with an `experiment_id` different from the journal's | Error: "run X belongs to experiment Y" |
| Journal without `experiment_id` (older runs) or unreadable | The run is a one-run experiment named after its `run_id` |
| `get_experiment` with an unknown id | Returns `None`; the user-facing message belongs to C |
| Two runs without an id started in the same second | They receive the same generated id and share an experiment; documented, unlikely |

## Testing

All unit tests: this sub-project changes nothing that runs on remote hosts (the
journal is written on the controller).

- Validation: valid and invalid ids; shape of the generated id.
- Resume: a run with a generated id resumes with its original config file
  (proves the hash exclusion); a different id on resume is rejected.
- Journal: `metadata.experiment_id` is written; `--experiment` beats the config
  value, which beats generation.
- Catalog: on run folders built in the test (two runs in one experiment, one in
  another, one older run without an id): grouping, ordering, `get_experiment`,
  `folder_experiment`.
- Link to A: `load_experiment(catalog.get_experiment(id).runs)` returns only
  that experiment's runs, using the real analytics fixtures.

## Out of scope

- **C — CLI, TUI, GUI and lifecycle wiring:** the experiment/folder picker
  with preview, `lb runs analyze --experiment/--root`, the summary before
  running and the result with the equivalent command, the working "Analyze"
  action in `lb runs list`, the end-of-run prompt, GUI parity.
- Experiments spanning several output folders.
