# Analytics: dataset unification — design

Date: 2026-10-09
Status: approved in conversation, pending written review
Scope: sub-project **A** of the analytics work (see "Out of scope")

## Goal

Load every dataset an experiment produced — across its runs, hosts, workloads
and repetitions — and unify them into a small set of tidy tables, so that the
performance of a machine can be analysed and, later, predicted. The prediction
methodology is a separate, later step; this design only has to give it data that
is complete, typed and joinable.

An experiment is a set of runs. If it has one run, that run's data is loaded; if
it has several, the data of all of them is combined. How an experiment is named
and selected is sub-project B; here the input is simply a list of runs.

## Decisions

| Topic | Decision |
|---|---|
| Unified form | Tidy tables are the source of truth. A wide "feature matrix" view is derived from them later, together with the methodology. |
| Storage | Parquet, one file per table, under `<data_export_dir>/<experiment>/`. The same tables are available in memory as pandas DataFrames through the API. |
| Schema knowledge | Every producer **declares** its datasets in a `datasets.json` manifest written next to the data. `lb_analytics` reads only manifests: no heuristics, no plugin imports. |
| Old runs | Not supported. Runs without manifests are reported as not loadable. |
| FaaS plugins | dfaas and peva_faas additionally export a `long` file; their legacy `results.csv` stays unchanged. |

## Architecture

| Layer | Adds | Why there |
|---|---|---|
| `lb_common` | The dataset descriptor model and read/write of `datasets.json`. | The only package both producers (`lb_plugins`, `lb_runner`) and `lb_analytics` may import. |
| `lb_plugins` | Each plugin declares the schemas of the files it exports. The default `WorkloadPlugin` export declares its own file. | Whoever writes a CSV is the only one who knows which columns are parameters and which are measurements. |
| `lb_runner` | After the plugin export, writes `<host>/<workload>/datasets.json` (plugin datasets plus collector samples) and `<host>/datasets.json` (`system_info.csv`). | The manifest is created on the remote host with the data and reaches the controller through the existing, verified collection. |
| `lb_analytics` | A loader: list of runs → five tables + load report; Parquet writer. | Keeps the `lb_analytics isolation` import contract intact. |
| `lb_app` | Re-exports the loader API for CLI/TUI/GUI. | Existing layered path; the UI wiring itself belongs to sub-project C. |

New dependency: `pyarrow` added to the `controller` extra (already in `uv.lock`
through the `peva_faas` extra and the dev group).

## Manifest and descriptor

`datasets.json` holds a list of descriptors. Paths are globs relative to the
directory containing the manifest.

Common fields:

- `name`: dataset identifier, unique within the manifest (e.g. `fio_plugin`).
- `path`: glob of the file(s).
- `shape`: `wide` | `long` | `timeseries`.
- `keys`: columns that identify a row or describe the configuration of the
  measurement (e.g. `repetition`, `n`, `nb`, `provider`). They become key or
  dimension columns, never metrics.
- `fixed`: constant key values for every row of the file (e.g.
  `{"repetition": 3, "collector": "PSUtilCollector"}`), for files whose keys are
  in their location rather than in their columns.
- `table`: target table. Defaults to `results` for `wide` and `long`, `samples`
  for `timeseries`; only the runner's `system_info.csv` sets `host_info`, whose
  values are text and therefore exempt from the numeric rule.

Shape-specific fields:

- `wide` — one row per repetition (or configuration), metrics as columns.
  `metrics`: list of entries, each either `{"column": ..., "unit": ...}` or
  `{"pattern": ..., "unit": ...}`. A pattern is a regex that must contain the
  named group `metric`; every other named group becomes a dimension. `unit` is a
  literal or a template naming another column of the same row
  (`{"unit_column": "{test}_unit"}`, used by unixbench).
  `exclude`: columns a pattern would otherwise match but that are not metrics
  (e.g. `generator_stdout`, `generator_returncode`).
- `long` — several rows per repetition, one measurement per row. Either
  `value_columns` (several measure columns, metric name = column name, each with
  a unit) or `metric_column` + `value_column`; units from `unit` or
  `unit_column`.
- `timeseries` — `time_column`; every other numeric column is a metric.

Example — stress_ng's dynamic columns:

```json
{"name": "stress_ng_plugin", "path": "*_plugin.csv", "shape": "wide",
 "keys": ["repetition"],
 "metrics": [{"pattern": "^generator_(?P<stressor>[a-z0-9-]+)_(?P<metric>.+)$"}],
 "exclude": ["generator_stdout", "generator_stderr", "generator_command",
             "generator_tags", "generator_max_retries", "generator_returncode"]}
```

`generator_cpu_bogo_ops` becomes metric `bogo_ops` with dimension
`stressor=cpu`.

Rules:

1. Only what is declared is loaded. Undeclared columns are ignored and listed in
   the load report.
2. Metrics are numeric. A value that does not convert is an error for that
   dataset, with file, column and row count; no partial rows are loaded.
3. Units are declared, never inferred.

### Declarations by producer

| Producer | Files | Shape |
|---|---|---|
| runner | `system_info.csv` (host level) | `long`: keys `category`, `name`; `value` is text and goes to `host_info`, not `results` |
| runner | `rep*/<workload>_rep*_<Collector>.csv` | `timeseries`, one descriptor per file with `fixed` repetition and collector |
| default `WorkloadPlugin` export (baseline and plugins without a custom export) | `<workload>_plugin.csv` | `wide`, `^generator_(?P<metric>.+)$` minus the standard excludes |
| stress_ng | `*_plugin.csv` | `wide`, pattern with `stressor` dimension |
| sysbench | `*_plugin.csv` | `wide`, default pattern |
| unixbench | `*_plugin.csv` | `wide`, pattern with `test` dimension; unit from `{test}_unit` |
| fio, dd, hpl, stream | `*_plugin.csv` | `wide`, explicit columns; hpl keys `n`, `nb`, `p`, `q`; stream key `compiler` |
| yabs | `yabs_plugin.csv` | `wide`, `^fio_(?P<block_size>[^_]+)_(?P<metric>.+)$` |
| yabs | `yabs_iperf.csv` | `long`, keys `mode`, `provider`, `location`; `value_columns` send/recv (Mbit/s), latency (ms) |
| geekbench | `*_plugin.csv`, `*_subtests.csv` | `wide` scores; `long` keyed by `subtest` |
| PTS (all profiles) | `*_pts_results.csv` | `long`, `metric_column` = `test`, keys `description`, `arguments`, `system`, `app_version`, `unit_column` = `scale` |
| dfaas, peva_faas | new `results_long.csv` | `long`, keys `config_id`, `function`, `rate`; one row per configuration × function × metric |
| dfaas, peva_faas | `metrics/*.csv` | `wide`, keys `config_id`, `iteration` |

## Unified tables

All tables share the keys `run_id`, `host`, `workload`, `repetition` (where
applicable), so they join directly.

| Table | One row per | Columns | Source |
|---|---|---|---|
| `runs` | run | `run_id`, `experiment_id` (empty until sub-project B), `created_at`, `config_hash`, `repetitions` | `run_journal.json` |
| `host_info` | machine attribute | `run_id`, `host`, `category`, `name`, `value` | `system_info.csv`, kept long like its source |
| `repetitions` | repetition | keys, `plugin`, `success`, `start_time`, `end_time`, `duration_seconds` | `<workload>_results.json` |
| `results` | measured value | keys, `plugin`, `dataset`, `metric`, `value` (float64), `unit`, one `dim_<name>` column per dimension | `wide` and `long` datasets |
| `samples` | sample × metric | keys, `collector`, `timestamp`, `metric`, `value` | `timeseries` datasets |

- Dimensions are real nullable `dim_*` string columns (about ten in total), so
  they filter directly in pandas, e.g. `results[results.dim_block_size == "4k"]`.
- `repetitions` is separate so failed repetitions can be excluded and collector
  samples can be aligned to each workload's time window.
- Every load also produces `load_report.json`: files read, files present but not
  declared, conversion errors, failed repetitions. The UI summary of
  sub-project C is built on it.

## API

```python
from lb_analytics.api import load_experiment

data = load_experiment(runs)  # runs: Sequence[RunInfo]
data.results  # pandas DataFrames: runs, host_info,
data.report  #   repetitions, results, samples
data.to_parquet(out_dir)  # five .parquet files + load_report.json
```

## Error handling

A localized problem never stops the experiment; it always lands in the load
report.

| Situation | Behaviour |
|---|---|
| Workload directory without `datasets.json` | Workload skipped, reported as "not loadable: no manifest" |
| Manifest invalid against the `lb_common` model | Workload skipped, error with the reason |
| Declared file missing | Error for that dataset; the others load |
| Non-numeric metric value | Error for that dataset with file, column, row count; no partial rows |
| Pattern matching no column | Warning (almost always a broken declaration) |
| File present but undeclared | Warning |

If nothing at all loads, the command fails; otherwise it succeeds and shows the
warnings.

## Testing

1. **Real fixtures.** Reduced samples of the outputs captured on Multipass VMs on
   2026-10-08 go to `tests/fixtures/`, one set per plugin, so every test runs on
   real formats rather than hand-written ones.
2. **Contract test over every registered plugin.** Run the export on the real
   `results.json` fixtures; the produced manifest must cover every numeric
   column of every exported CSV, and every declared pattern must match at least
   one column.
3. **Loader tests.** A synthetic experiment assembled from the fixtures (two
   runs, two hosts, several workloads): schema of the five tables, hand-checked
   values (e.g. stress_ng `bogo_ops` for `stressor=cpu`), load report content,
   Parquet write and re-read.
4. **Real verification on Multipass.** Re-run experiments with every plugin
   except Geekbench (it needs a Pro license), unify them, and reconcile: the
   count of declared numeric cells in the CSVs equals the rows in `results`, and
   every repetition appears in `repetitions`.

## Out of scope

- **B — experiment identity and selection:** `experiment_id` in the config and in
  `lb run`, written to the journal; grouping by experiment or by output folder.
- **C — CLI, TUI, GUI and lifecycle wiring:** the agreed TUI flow (experiment
  or folder picker with preview, summary before running, result with the
  equivalent CLI command), `lb runs analyze --experiment/--root`, the working
  "Analyze" action in `lb runs list`, the end-of-run prompt and `--analyze` flag,
  then GUI parity.
- **D — prediction methodology** and the derived wide feature view.
