# Analytics: experiment analysis in CLI, TUI and GUI — design

Date: 2026-10-10
Status: approved in conversation (the user approved spec and plan in advance)
Scope: sub-project **C** of the analytics work. A (dataset unification) and B
(experiment identity) are merged. This one puts them in front of the user.

## Goal

Let a user pick an experiment (or a whole output folder), see what its
unification will produce, run it, and get the Parquet tables plus the CLI
command that reproduces the run. The same flow exists in the CLI, the TUI and
the GUI, all on one `lb_app` service. The per-run `aggregate` analytics it
replaces is removed: everything it computed is in the `samples` table, at a
finer grain.

## Decisions

| Topic | Decision |
|---|---|
| Unit of analysis | An `ExperimentInfo` from B: an experiment (runs sharing an `experiment_id`) or the folder (every run in the output folder). |
| Old `aggregate` analytics | Removed, not kept beside the new flow (user's choice). |
| Where the logic lives | One `UnificationService` in `lb_app`; CLI, TUI and GUI only present it. |
| Summary before writing | The data is loaded once; the summary is built from the loaded tables (exact, not an estimate); confirming writes what was loaded. |
| Output | `data_exports/<experiment id>/` (the config's `data_export_dir`), one Parquet per table plus `load_report.json`, overwriting the previous unification of the same experiment. The folder entry writes to `data_exports/_folders/<folder name>/`: experiment ids start with a letter or digit, so a folder and an experiment sharing a name never overwrite each other. |
| Filters | Optional host and workload filters, applied to every table that has the column before writing. Selecting every host (or workload) is the same as no filter. |

## `lb_app`: `UnificationService`

File `lb_app/services/unification_service.py`, exported from `lb_app.api`.

| Element | Contract |
|---|---|
| `UnificationService(catalog: RunCatalogService, export_root: Path)` | `export_root` is the config's `data_export_dir`. |
| `list_targets() -> list[ExperimentInfo]` | Experiments newest first, then the folder entry; the folder entry only when the folder has runs. Empty folder: `[]`. |
| `find(experiment_id: str \| None) -> ExperimentInfo` | `None` means the folder. Unknown id: `UnificationError` naming up to five recent ids. Folder with no runs: `UnificationError("no runs in <dir>")`. |
| `prepare(experiment, hosts=(), workloads=()) -> UnificationPreview` | Checks `pyarrow` is importable (else `UnificationError` naming `pip install 'linux-benchmark-lib[controller]'`), runs `load_experiment(experiment.runs)`, applies the filters. |
| `write(preview) -> list[Path]` | Refuses an empty preview (`UnificationError`), else `preview.data.to_parquet(preview.out_dir)`; a write failure (disk, permissions, pyarrow) becomes a `UnificationError` naming the folder, never a traceback. |
| `UnificationPreview` | `experiment`, `data: ExperimentData` (filtered), `hosts`, `workloads` (the filters, empty = all), `out_dir`, `command` (the equivalent `lb runs analyze …`, shell-quoted, with `--root` and the filters), `row_counts` (table → rows), `is_empty`, `summary_rows()` (label/value pairs every UI renders). |
| `UnificationError(Exception)` | Every user-facing failure; the message is shown as is. |

`ExperimentData.filter(hosts, workloads)` in `lb_analytics` does the filtering
(host filter on `host_info`, `repetitions`, `results`, `samples`; workload
filter on the last three; `runs` untouched; the load report is carried over).

## CLI: `lb runs analyze`

Replaces the current command; the positional `RUN_ID` and `--kind` go.

| Form | Behaviour |
|---|---|
| `--experiment/-e ID` | Unify that experiment. |
| `--folder` | Unify every run of the folder as one experiment. |
| `--root/-r DIR`, `--config/-c FILE` | As today: where to look; defaults from the config. |
| `--host/-H`, `--workload/-w` (repeatable) | Filters. |
| Both `--experiment` and `--folder` | Error, exit 1. |
| Neither, interactive terminal | The TUI flow below. |
| Neither, headless or no TTY | Error naming `--experiment` and `--folder`, exit 1. |

With an option the command prints the summary and writes without asking
(scripts), then prints the result. Exit codes: 0 when written (load errors are
reported as a warning: the data is partial, not missing); 1 for every
`UnificationError`, including "no rows after the filters".

## TUI flow

`lb_ui/flows/unification.py`, used by `lb runs analyze`, `lb runs list` and the
end of `lb run`.

1. **Pick** (skipped when an experiment is preselected): one list, experiments
   newest first, then the folder entry; each item's preview lists the runs
   (id, date, hosts, workloads).
2. **Summary**: `summary_rows()` as a table (experiment, kind, runs, hosts,
   workloads, rows per table, failed repetitions, load errors and warnings,
   output folder). Actions: **Unify** (absent when the preview is empty),
   **Filters** (pick-many of hosts, then of workloads, all preselected; then
   back to the summary), **Cancel**.
3. **Result**: the files written with their row counts, the output folder,
   and `Equivalent command: lb runs analyze …`.

## Lifecycle

| Entry | Behaviour |
|---|---|
| `lb runs list` → **Analyze** | The flow with that run's experiment preselected (starts at the summary). |
| End of `lb run`, interactive terminal | "Unify experiment <id> now?", default **No**; yes unifies the whole experiment (earlier runs included) and prints the result. |
| `lb run --analyze` | Unifies at the end without asking, headless included. |
| `lb run --no-analyze` | Never asks and never unifies (unattended loops in a terminal). |

Both run after "Run completed."; a run that did not start never gets there.

## GUI

The analytics view keeps its layout and loses the kind combo.

| Area | Content |
|---|---|
| Left | Experiments table (experiment, runs, hosts, workloads, last run); the folder entry is the first row. |
| Right, top | The selected experiment's runs. |
| Filters | Hosts and workloads of the experiment, all selected by default. |
| Actions | **Prepare** loads in a background worker and fills the summary table from `summary_rows()`; **Unify** (enabled only for a non-empty preview, cleared when the selection or filters change) writes in a background worker. |
| Result | Files with row counts, output folder (double-click opens it), the equivalent command in a read-only field with a Copy button. |

`AnalyticsViewModel` holds no logic beyond state: it calls `UnificationService`,
obtained from the configured `RunCatalogServiceWrapper`. The worker runs any
callable (prepare or write) and emits its result or error.

## Removal

`AnalyticsService`, `AnalyticsRequest`, `AnalyticsKind` (`lb_analytics.engine`),
`DataHandler`, `TestResult`, `Reporter`, `aggregate_cli`, `aggregate_psutil`
(both copies), `CollectorPlugin.aggregator`, the GUI `AnalyticsServiceWrapper`,
`UIContext.analytics_service`, their exports and tests. `matplotlib` and
`seaborn` were used only by `Reporter`: they leave the `controller` extra, the
dev group and the doctor checks (`pyarrow` takes their place there). Docs that
describe `lb runs analyze RUN_ID` or `--kind aggregate` are rewritten.

## Error handling

| Situation | Behaviour |
|---|---|
| Unknown `--experiment` | `UnificationError` listing recent experiments; exit 1 |
| Folder without runs | "no runs in <dir>"; the TUI and GUI lists are empty |
| Load errors in the report | Listed in the summary; writing proceeds; CLI warning, exit 0 |
| No rows after the filters | The summary says so, Unify unavailable; CLI exit 1 |
| `pyarrow` missing | Message naming the `controller` extra, before loading |
| Journal of the finished run has no experiment id | The end-of-run step warns and skips |

## Testing

- `ExperimentData.filter`: hosts, workloads, both, none.
- `UnificationService` on the real plugin fixtures (`tests/fixtures/plugin_outputs`,
  as in B's link test): target order, `find` (folder, unknown id, empty folder),
  prepare with and without filters, "all selected" equals no filter, write and
  overwrite, empty preview refused, command text, `pyarrow` missing.
- CLI with `CliRunner`: `--experiment`, `--folder`, both, neither (headless),
  unknown id, filters leaving nothing, `lb run --analyze` wiring.
- TUI flow with `HeadlessUI` and a scripted picker: pick → summary → unify;
  filters then unify; cancel; preselected experiment; end-of-run prompt.
- GUI: view-model tests (experiments listing, selection defaults, prepare,
  unify, Unify disabled on an empty preview) and an offscreen construction test
  of the view.
- Removal: `lb_app.api` no longer exports `AnalyticsService`.

## Out of scope

- D: methodology (models and predictions on the unified tables).
- Charts or reports built on the unified tables.
- Experiments spanning several output folders (B's known limit).
