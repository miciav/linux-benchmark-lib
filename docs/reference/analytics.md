# Analytics

Unify the datasets of an experiment (one run or many) into analysis-ready
tables.

## From the CLI, TUI and GUI

- `lb runs analyze --experiment ID` (or `--folder` for every run of the output
  folder, written to `data_exports/_folders/<folder>/`) writes the tables to
  `data_exports/<experiment>/`, after printing a
  summary; `--host` and `--workload` filter them. Without either option, an
  interactive terminal opens a picker with a preview, then the summary with
  *Unify*, *Filters* and *Cancel*. The result ends with the equivalent command.
- `lb runs list` → *Analyze* opens the same flow on the run's experiment.
- `lb run --analyze` unifies the run's experiment when the run ends; an
  interactive `lb run` asks instead (default No), and `--no-analyze` never
  asks.
- The GUI *Analytics* view lists the experiments, prepares the same summary and
  unifies in the background.

All of them use `UnificationService` from `lb_app.api`.

::: lb_app.services.unification_service.UnificationService
::: lb_app.services.unification_service.UnificationPreview

## Unified datasets

`load_experiment(runs)` reads every `datasets.json` manifest of the given runs
and returns `runs`, `host_info`, `repetitions`, `results` and `samples` as pandas
DataFrames plus a `LoadReport`; `ExperimentData.to_parquet(dir)` writes them.

::: lb_analytics.unify.loader.load_experiment
::: lb_analytics.unify.experiment.ExperimentData

Runs are grouped into experiments by `RunCatalogService`: `list_experiments()`,
`get_experiment(id)` and `folder_experiment()` return `ExperimentInfo` objects
whose `runs` feed `load_experiment` directly:

    experiment = RunCatalogService(output_dir).get_experiment("exp-20261009-151200")
    data = load_experiment(experiment.runs)
