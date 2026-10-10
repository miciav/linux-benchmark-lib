import math

import pandas as pd
import pytest

from lb_analytics.api import (
    Model,
    PredictionError,
    evaluate,
    fit,
    loo_predictions,
    predict,
)

pytestmark = pytest.mark.unit_analytics

TARGET = "fio/fio/results/iops"
CORES = (1, 2, 3, 8, 16)
NOISE = (1.0, 1.02, 0.98, 1.01, 0.99)


def _law(cores: float) -> float:
    return 50 * cores**0.9


def _frames(
    cores: tuple[int, ...] = CORES, noise: tuple[float, ...] = NOISE
) -> tuple[pd.DataFrame, pd.DataFrame]:
    names = [f"m{c}" for c in cores]
    machines = pd.DataFrame(
        {
            "machine": names,
            "physical_cpus": [float(c) for c in cores],
            "mem_bytes": [8e9] * len(cores),
            "disk_rotational": [0.0] * len(cores),
        }
    )
    targets = pd.DataFrame(
        {
            "machine": names,
            "target": TARGET,
            "workload": "fio",
            "metric": "iops",
            "unit": "op/s",
            "median": [_law(c) * n for c, n in zip(cores, noise, strict=True)],
            "iqr": [_law(c) * 0.02 for c in cores],
            "n": 3,
        }
    )
    return machines, targets


def test_fit_recovers_the_exponent() -> None:
    model = fit(*_frames(), TARGET, ["physical_cpus"])
    assert model.coefficients["physical_cpus"] == pytest.approx(0.9, abs=0.05)
    assert model.unit == "op/s"
    assert model.machines == ("m1", "m2", "m3", "m8", "m16")
    assert model.feature_ranges == {"physical_cpus": (1.0, 16.0)}
    assert 0 < model.max_log_error < 0.1
    assert model.rel_iqr == pytest.approx(0.02, rel=0.1)


def test_predict_range_contains_an_unseen_machine() -> None:
    model = fit(*_frames(), TARGET, ["physical_cpus"])
    prediction = predict(model, {"physical_cpus": 6})
    assert prediction.low < _law(6) < prediction.high
    assert prediction.value == pytest.approx(_law(6), rel=0.05)
    assert prediction.unit == "op/s"
    assert not prediction.extrapolated


def test_predict_accepts_a_machines_row() -> None:
    machines, targets = _frames()
    model = fit(machines, targets, TARGET, ["physical_cpus"])
    row = machines.iloc[2]
    assert predict(model, row).value == pytest.approx(_law(3), rel=0.05)


def test_predict_outside_the_training_range_warns() -> None:
    model = fit(*_frames(), TARGET, ["physical_cpus"])
    with pytest.warns(UserWarning, match="physical_cpus=64"):
        prediction = predict(model, {"physical_cpus": 64})
    assert prediction.extrapolated


def test_predict_refuses_a_missing_feature() -> None:
    model = fit(*_frames(), TARGET, ["physical_cpus"])
    with pytest.raises(PredictionError, match="physical_cpus"):
        predict(model, {"mem_bytes": 8e9})


def test_model_json_round_trip() -> None:
    model = fit(*_frames(), TARGET, ["physical_cpus"])
    assert Model.from_json(model.to_json()) == model


def test_fit_refuses_an_unknown_target_and_lists_similar_ones() -> None:
    with pytest.raises(PredictionError, match="similar: fio/fio/results/iops"):
        fit(*_frames(), "iops", ["physical_cpus"])
    with pytest.raises(PredictionError, match="Unknown target 'nope'"):
        fit(*_frames(), "nope", ["physical_cpus"])


def test_fit_refuses_an_unknown_feature() -> None:
    with pytest.raises(PredictionError, match="Unknown feature 'cores'"):
        fit(*_frames(), TARGET, ["cores"])


def test_fit_refuses_too_few_machines() -> None:
    machines, targets = _frames()
    with pytest.raises(PredictionError, match="at least 3"):
        fit(machines, targets.head(2), TARGET, ["physical_cpus"])


def test_fit_refuses_a_missing_feature_value() -> None:
    machines, targets = _frames()
    machines.loc[0, "physical_cpus"] = math.nan
    with pytest.raises(PredictionError, match="'physical_cpus' is missing on m1"):
        fit(machines, targets, TARGET, ["physical_cpus"])


def test_fit_refuses_a_constant_feature() -> None:
    with pytest.raises(PredictionError, match="'mem_bytes' has the same value"):
        fit(*_frames(), TARGET, ["mem_bytes"])


def test_fit_refuses_a_non_positive_target() -> None:
    machines, targets = _frames()
    targets.loc[0, "median"] = 0.0
    with pytest.raises(PredictionError, match="not positive on m1"):
        fit(machines, targets, TARGET, ["physical_cpus"])


def test_binary_feature_enters_without_log() -> None:
    machines, targets = _frames()
    machines["disk_rotational"] = [1.0, 1.0, 0.0, 0.0, 0.0]
    model = fit(machines, targets, TARGET, ["physical_cpus", "disk_rotational"])
    assert set(model.coefficients) == {"physical_cpus", "disk_rotational"}
    assert predict(model, {"physical_cpus": 2, "disk_rotational": 0}).value > 0


def test_nearest_baseline_uses_the_closest_machine() -> None:
    machines, targets = _frames()
    held_out = loo_predictions(machines, targets, TARGET, ["physical_cpus"])
    row = held_out[(held_out.machine == "m3") & (held_out.method == "nearest")]
    m2 = targets.loc[targets.machine == "m2", "median"].item()
    assert row["predicted"].item() == pytest.approx(m2)


def test_loo_predictions_has_every_machine_and_method() -> None:
    held_out = loo_predictions(*_frames(), TARGET, ["physical_cpus"])
    assert len(held_out) == len(CORES) * 3
    assert set(held_out.method) == {"model", "mean", "nearest"}


def test_evaluate_says_the_model_beats_the_baselines() -> None:
    report = evaluate(*_frames(), ["physical_cpus"])
    model_row = report[report.method == "model"].iloc[0]
    assert model_row["beats_baselines"]
    assert model_row["median_abs_pct_error"] < 5
    assert model_row["machines"] == len(CORES)
    assert set(report.method) == {"model", "mean", "nearest"}


def test_evaluate_skips_targets_it_cannot_fit() -> None:
    machines, targets = _frames()
    sparse = targets.head(2).assign(target="dd/dd/results/bw")
    zero = targets.assign(target="stream/stream/results/errors", median=0.0)
    report = evaluate(machines, pd.concat([targets, sparse, zero]), ["physical_cpus"])
    skipped = report[report.method == "skipped"].set_index("target")
    assert "at least 3" in skipped.loc["dd/dd/results/bw", "note"]
    assert "not positive" in skipped.loc["stream/stream/results/errors", "note"]
    assert (report[report.target == TARGET].method != "skipped").all()


def test_evaluate_filters_targets_by_text() -> None:
    machines, targets = _frames()
    other = targets.assign(target="dd/dd/results/bw")
    report = evaluate(machines, pd.concat([targets, other]), ["physical_cpus"], "dd/")
    assert set(report.target) == {"dd/dd/results/bw"}


def test_fit_refuses_collinear_features() -> None:
    machines, targets = _frames()
    machines["mem_bytes"] = machines["physical_cpus"] * 2 * 1024**3
    with pytest.raises(PredictionError, match="collinear"):
        fit(machines, targets, TARGET, ["physical_cpus", "mem_bytes"])


def test_a_fold_blind_to_a_feature_predicts_the_mean() -> None:
    names = ["a", "b", "c", "d"]
    machines = pd.DataFrame({"machine": names, "physical_cpus": [2.0, 2.0, 2.0, 4.0]})
    targets = pd.DataFrame(
        {
            "machine": names,
            "target": TARGET,
            "workload": "fio",
            "metric": "iops",
            "unit": "op/s",
            "median": [100.0, 110.0, 90.0, 190.0],
            "iqr": 0.0,
            "n": 1,
        }
    )
    held_out = loo_predictions(machines, targets, TARGET, ["physical_cpus"])
    d = held_out[held_out.machine == "d"].set_index("method")["predicted"]
    assert d["model"] == pytest.approx(d["mean"])
