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

## Prediction

`lb_analytics.api` can answer, per benchmark metric, how much of a machine's
performance its specifications explain, and predict a machine that was not
benchmarked. It is a library for notebooks; there is no command.

    from lb_analytics.api import evaluate, fit, load_experiment, machines, predict, targets
    from lb_app.api import RunCatalogService

    catalog = RunCatalogService(output_dir)
    data = [load_experiment(catalog.get_experiment(e).runs) for e in experiment_ids]
    m, t = machines(*data), targets(*data)
    report = evaluate(m, t, ["physical_cpus"], targets_filter="stress_ng")
    target = "stress_ng/stress_ng/stress_ng_plugin/bogo_ops_per_s_real[stressor=cpu]"
    model = fit(m, t, target, ["physical_cpus"])

    new = machines(load_experiment(catalog.get_experiment("exp-new-host").runs))
    predict(model, new.iloc[0])  # Prediction(value, low, high, unit, extrapolated)

Pass the same experiments to `machines` and `targets`: the two tables are
joined on the `machine` name.

- `machines` has one row per machine: a host with one set of features
  (cores, MHz, caches, memory, disk). The same host re-created with another
  size is another machine (`host#<hash>`); small drifts (a few KiB of
  MemTotal, bogomips, swap) do not split a host.
- `targets` has one row per machine and target, with the median over the
  successful repetitions, the IQR and the count.
- `fit` is a log-linear regression: a coefficient of 0.9 on `physical_cpus`
  means doubling the cores multiplies the metric by about 1.87.
- `evaluate` leaves each machine out in turn and compares the model with the
  mean of the other machines and with the nearest one on the chosen features.
  A model is worth using only where `beats_baselines` is true.
- `predict` gives a range: the worst error seen leaving machines out, plus the
  run-to-run noise. A feature outside the training range warns that the
  prediction is an extrapolation.

Limits: the machines must differ in the chosen features (identical VMs explain
nothing), and features that move together (cores and memory on VM sizes that
scale both) are refused as collinear; use one to three features with fewer than
15 machines; the kernel
reports virtio disks as rotational, so `disk_rotational` is unreliable on VMs.
The features of a machine come from any run on it, so a short `baseline` run is
enough to predict it.

::: lb_analytics.predict.features.machines
::: lb_analytics.predict.features.targets
::: lb_analytics.predict.model.fit
::: lb_analytics.predict.model.evaluate
::: lb_analytics.predict.model.loo_predictions
::: lb_analytics.predict.model.predict
