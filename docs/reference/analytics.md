# Analytics

Services for running post-processing on stored benchmark runs.

::: lb_analytics.engine.service.AnalyticsService
::: lb_analytics.engine.service.AnalyticsRequest

## Unified datasets

`load_experiment(runs)` reads every `datasets.json` manifest of the given runs
and returns `runs`, `host_info`, `repetitions`, `results` and `samples` as pandas
DataFrames plus a `LoadReport`; `ExperimentData.to_parquet(dir)` writes them.

::: lb_analytics.unify.loader.load_experiment
::: lb_analytics.unify.experiment.ExperimentData
