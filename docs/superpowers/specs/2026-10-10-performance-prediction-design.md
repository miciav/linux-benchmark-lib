# Analytics: predicting performance from machine specifications — design

Date: 2026-10-10
Status: design approved in conversation; written spec awaiting review
Scope: sub-project **D** of the analytics work. A (dataset unification), B
(experiment identity) and C (CLI/TUI/GUI wiring) are merged. D is the
methodology on top of the unified tables.

## Goal

Answer, for each benchmark metric, "how much of a machine's performance do its
specifications explain?", and, where the answer is "enough", predict the
metric for a machine that was not benchmarked, with an honest error range.

## Decisions

| Topic | Decision |
|---|---|
| Question | From specifications (`host_info`) to performance (`results`). |
| Machine park | Few machines, 3 to 15. Simple, interpretable models; leave-one-machine-out validation; uncertainty stated. |
| Delivery | Python library in `lb_analytics`, used from a notebook. No CLI or GUI command. |
| Model | Per-target log-linear regression on 1–3 hand-picked features, solved with `numpy.linalg.lstsq`. |
| Baselines | Every model is compared with `mean` (geometric mean of the other machines) and `nearest` (the closest machine on the chosen features). |
| Dependencies | pandas and numpy only, both already required. No scikit-learn. |

The current real data (three hosts, all the same aarch64 4-core 8 GB VM) cannot
fit any model: identical specifications carry no information about their
effect. Using the methodology needs machines whose specifications differ, for
example Multipass VMs of different sizes.

## Inputs

Functions in `lb_analytics/predict/features.py`. Both take one or more
`ExperimentData` and concatenate them, because machines usually come from
different experiments or folders.

### `machines(*data) -> pd.DataFrame`

One row per machine. A machine is `host` plus the features that do not drift
between its runs: logical and physical CPUs, threads per core, sockets, L2 and
L3 cache, `disk_rotational`, and memory and disk size in whole GiB (MemTotal
moves by a few KiB across kernels). `bogomips`, the current MHz and swap are
left out of the identity. The same hostname re-created with another size is a
different machine. The `meta/fingerprint` value is not used: it hashes memory
usage, services and modules too, so it changes on every run. The `machine`
column is the host name when the host has one identity in the data, and
`host#<4 hex digits of a hash of its identity>` when it has several, so a
variant's name does not depend on which experiments are passed. Feature values
come from the machine's first run (by `created_at`). Missing values in
`host_info` (`pd.NA`, empty cells) count as absent.

Numeric features (NaN when absent):

| Column | Source in `host_info` |
|---|---|
| `logical_cpus` | cpu `logical_cpus`, else `cpu(s)` |
| `physical_cpus` | cpu `physical_cpus` |
| `threads_per_core` | cpu `thread(s)_per_core` |
| `sockets` | cpu `socket(s)` |
| `cpu_mhz` | cpu `cpu_max_mhz`, else `cpu_mhz` |
| `bogomips` | cpu `bogomips` |
| `l2_bytes`, `l3_bytes` | cpu `l2_cache`, `l3_cache` ("1 MiB (4 instances)" → total bytes; "512 KiB" → bytes) |
| `mem_bytes` | memory `total_bytes` |
| `swap_bytes` | memory `swap_total_bytes` |
| `disk_bytes`, `disk_rotational` | the `disk` entry with the largest `size_bytes` (JSON value; entries without a size are ignored); `rotational` as 0/1 |

Descriptive columns, not used as model inputs: `machine`, `host`, `arch`
(kernel `machine`), `cpu_model` (cpu `model_name`), `cpu_vendor` (cpu
`vendor_id`), `virtualized` (true when cpu `hypervisor_vendor` exists or
`bios_vendor_id` is QEMU or KVM), `kernel` (kernel `release`), `runs` (the run
ids it appears in).

`disk_rotational` is reported as the kernel says; on virtio disks it is `1`
even on SSD-backed hosts, so it is unreliable on VMs. The docs say so.

### `targets(*data) -> pd.DataFrame`

One row per machine and target. A target is `workload`, `plugin`, `dataset`,
`metric` plus every non-null `dim_*` column of the result row, rendered as one
string `target` (`fio/fio/results/iops[block_size=4k,mode=randread]`).
A trailing `-rep<N>` is dropped from the dataset name: dfaas and peva_faas
write one dataset per repetition (`metrics-<config>-iter1-rep2`), and without
this each repetition would be a target of its own.
Repetitions whose `repetitions.success` is false are excluded. A run whose
`host_info` is missing counts for its host's machine when the host has only one;
otherwise (a host never described, such as a load generator, or one with
several sizes) its results are left out with a warning. Columns:
`machine`, `target`, `workload`, `metric`, `unit`, `median`, `iqr`, `n`
(repetitions used). Targets are not pre-filtered: the notebook chooses which
ones matter.

## Models

Functions in `lb_analytics/predict/model.py`.

### `fit(machines, targets, target, features) -> Model`

Fits `log(median) = b0 + Σ bᵢ·xᵢ`, where `xᵢ = log(featureᵢ)` for every
feature except `disk_rotational`, which enters as 0/1. The
coefficients read as elasticities: `b = 0.9` on `physical_cpus` means doubling
the cores multiplies the metric by about 1.87.

`fit` raises `PredictionError` when:

- the target is unknown (the message lists up to five targets containing the
  given text);
- fewer than `len(features) + 2` machines have the target;
- a feature is NaN for a training machine, or constant across them (the
  message names the feature);
- a log-transformed feature or the target median is ≤ 0;
- the features are collinear on the training machines (the design matrix has
  rank below `len(features) + 1`, e.g. cores and memory on VM sizes that scale
  both), so their effects cannot be told apart.

`Model` is a frozen dataclass: `target`, `unit`, `features`, `intercept`,
`coefficients` (feature → value), `machines` (training machine ids),
`feature_ranges` (feature → min, max), `max_log_error` (from validation, below),
`rel_iqr` (median of `iqr / median` across the training machines measured at
least twice; `None` when none was), `xtx_inv` (the inverse of XᵀX of the design
matrix) and `max_leverage` (the largest leverage of a training machine).
`to_json()` / `Model.from_json(text)` round-trip it.

`fit` runs the leave-one-machine-out loop itself to fill `max_log_error`, so a
fitted model always carries its validation error.

### `evaluate(machines, targets, features, targets_filter=None) -> pd.DataFrame`

For each target (all, or those whose name contains `targets_filter`) with
enough machines: leave each machine out, fit on the rest, predict it. Features
are centred on the remaining machines before the fit, so a fold where a feature
is constant on the rest predicts their mean instead of an arbitrary value. The same
loop runs for the two baselines:

- `mean`: the geometric mean of the other machines' medians;
- `nearest`: the median of the other machine closest in Euclidean distance on
  the chosen features, after the same log transform and standardisation by the
  training machines' mean and standard deviation (a feature with zero standard
  deviation is left out of the distance).

One row per target and method (`model`, `mean`, `nearest`): `target`,
`method`, `machines`, `median_abs_pct_error`, `max_abs_pct_error`. A
`beats_baselines` column is true on the `model` row when its median error is
below both baselines'. Targets skipped for the reasons `fit` would raise are
listed in a row with `method = "skipped"` and the reason in `note`. An empty
or unknown feature list is not per target: `evaluate` raises `PredictionError`
once.

### `loo_predictions(machines, targets, target, features) -> pd.DataFrame`

The individual held-out predictions behind `evaluate` for one target: one row
per machine and method with `actual`, `predicted`, `pct_error`. For inspection
and plots in the notebook.

### `predict(model, machine) -> Prediction`

`machine` is a row of `machines(...)` (a `pd.Series`) or a mapping of feature
values. `Prediction` is a frozen dataclass: `value`, `low`, `high`, `unit`,
`extrapolated`.

- `value = exp(b0 + Σ bᵢ·xᵢ)`.
- The range is `value × exp(±e)`, where `e = max_log_error + log(1 + rel_iqr)`:
  the worst error seen in validation plus the run-to-run noise of the target.
  With at most 15 machines a quantile has no statistical meaning; the observed
  maximum is the honest, conservative choice.
- A feature outside the training range sets `extrapolated = True` and emits a
  `warnings.warn` naming the feature. A point whose leverage `x₀ᵀ(XᵀX)⁻¹x₀`
  exceeds `max_leverage` (a combination of features unlike any training
  machine, each one in range) does the same.
- When `rel_iqr` is `None` the noise term is 0 and `predict` warns that the
  range covers only the validation error.
- A missing or non-positive feature raises `PredictionError`.

A machine that was never benchmarked gets its features from any run on it:
`host_info` is collected on every run, so a short `baseline` workload run is
enough.

## Public API

`lb_analytics/api.py` adds `machines`, `targets`, `fit`, `evaluate`,
`loo_predictions`, `predict`, `Model`, `Prediction`, `PredictionError`.

## Testing

In `tests/unit/lb_analytics/`, on synthetic `ExperimentData` built in the tests
unless stated:

- Machines following `metric = 50 · physical_cpus^0.9`, with small noise:
  `fit` recovers 0.9 within 0.05; `evaluate` gives `beats_baselines = True`;
  the `predict` range contains the true value of a held-out machine.
- One test per `fit` refusal: unknown target, too few machines, NaN feature,
  constant feature, non-positive value.
- `nearest` picks the expected machine.
- The same host with two different sizes yields two machines (`h1#…`), with
  names independent of the other experiments passed; small drifts do not split
  a host; `pd.NA` values in `host_info` count as absent.
- Collinear features are refused; a fold blind to a feature predicts the mean.
- Failed repetitions are excluded from `targets`; `dim_*` values appear in the
  target name.
- `predict` on an out-of-range feature warns and sets `extrapolated`.
- `Model` JSON round-trip.
- Feature parsing on the real fixture `tests/fixtures/plugin_outputs/_host/system_info.csv`
  (ARM VM: no MHz, no caches, `virtualized` true), plus x86-style strings for
  cache sizes and MHz.

## Documentation

A "Prediction" section in `docs/reference/analytics.md`: the question it
answers, a notebook example (load experiments, `machines`, `targets`,
`evaluate`, `fit`, `predict`), how to read coefficients and the range, and the
limits (specifications must vary; `disk_rotational` on VMs; extrapolation).

## Housekeeping

`lb_analytics/engine/` and `lb_analytics/reporting/` remain on disk holding only
untracked `__pycache__` from the removal in C; they are deleted.

## Out of scope

- CLI or GUI commands (added once a model shows an acceptable error).
- Automatic feature selection.
- Non-linear models.
- Per-metric-family physical scaling against a reference machine.
- Charts (the notebook draws them from `loo_predictions`).
