"""Log-linear models of one target over machine features.

With 3 to 15 machines every model is validated by leaving one machine out and
compared with two baselines: the mean of the other machines and the nearest
one on the chosen features.
"""

from __future__ import annotations

import json
import math
import warnings
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from lb_analytics.predict.features import BINARY_FEATURES, FEATURES, to_number

METHODS = ("model", "mean", "nearest")
EVALUATE_COLUMNS = [
    "target",
    "method",
    "machines",
    "median_abs_pct_error",
    "max_abs_pct_error",
    "beats_baselines",
    "note",
]


class PredictionError(ValueError):
    """A model cannot be fitted or used; the message is meant for the user."""


@dataclass(frozen=True)
class Model:
    target: str
    unit: str
    features: tuple[str, ...]
    intercept: float
    coefficients: dict[str, float]
    machines: tuple[str, ...]
    feature_ranges: dict[str, tuple[float, float]]
    max_log_error: float
    rel_iqr: float | None
    xtx_inv: tuple[tuple[float, ...], ...]
    max_leverage: float

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, text: str) -> Model:
        raw = json.loads(text)
        raw["features"] = tuple(raw["features"])
        raw["machines"] = tuple(raw["machines"])
        raw["feature_ranges"] = {k: tuple(v) for k, v in raw["feature_ranges"].items()}
        raw["xtx_inv"] = tuple(tuple(row) for row in raw["xtx_inv"])
        return cls(**raw)


@dataclass(frozen=True)
class Prediction:
    value: float
    low: float
    high: float
    unit: str
    extrapolated: bool


def fit(
    machines: pd.DataFrame,
    targets: pd.DataFrame,
    target: str,
    features: Sequence[str],
) -> Model:
    """Fit ``log(median) = b0 + Σ bᵢ·log(featureᵢ)`` for one target.

    ``disk_rotational`` enters as 0/1 instead of its log. The returned model
    carries its leave-one-machine-out error, which sets the range of
    ``predict``, and the run-to-run noise of machines measured at least twice
    (``None`` when none was).
    """
    features = list(features)
    table = _table(machines, targets, target, features)
    design = _design(table, features)
    coef = _solve(design, np.log(table["median"].to_numpy(float)))
    # _table refused collinear features, so the inverse exists.
    xtx_inv = np.linalg.inv(design.T @ design)
    held_out = _loo(table, features)
    held_out = held_out[held_out["method"] == "model"]
    ratios = held_out["predicted"].to_numpy(float) / held_out["actual"].to_numpy(float)
    log_errors = np.abs(np.log(ratios))
    repeated = table["n"] >= 2
    rel_iqr = (table["iqr"] / table["median"])[repeated]
    return Model(
        target=target,
        unit=_unit(table),
        features=tuple(features),
        intercept=float(coef[0]),
        coefficients={f: float(c) for f, c in zip(features, coef[1:], strict=True)},
        machines=tuple(table["machine"]),
        feature_ranges={
            f: (float(table[f].min()), float(table[f].max())) for f in features
        },
        max_log_error=float(log_errors.max()),
        rel_iqr=float(rel_iqr.median()) if repeated.any() else None,
        xtx_inv=tuple(tuple(float(v) for v in row) for row in xtx_inv),
        max_leverage=float(_leverage(design, xtx_inv).max()),
    )


def predict(model: Model, machine: Mapping[str, Any] | pd.Series) -> Prediction:
    """Predict ``model.target`` for one machine, with the model's range.

    The range is the worst leave-one-machine-out error plus the target's
    run-to-run noise. A feature outside the training range, or a combination
    of features unlike any training machine, warns and sets ``extrapolated``.
    """
    log_value = model.intercept
    extrapolated = False
    point = [1.0]
    for feature in model.features:
        x = to_number(machine.get(feature))
        if math.isnan(x) or (x <= 0 and feature not in BINARY_FEATURES):
            raise PredictionError(
                f"Feature '{feature}' is missing or not positive "
                f"({machine.get(feature)!r})."
            )
        low, high = model.feature_ranges[feature]
        if not low <= x <= high:
            extrapolated = True
            warnings.warn(
                f"{feature}={x:g} is outside the training range "
                f"[{low:g}, {high:g}]: the prediction is an extrapolation.",
                stacklevel=2,
            )
        term = x if feature in BINARY_FEATURES else math.log(x)
        point.append(term)
        log_value += model.coefficients[feature] * term
    row = np.array([point])
    leverage = float(_leverage(row, np.array(model.xtx_inv))[0])
    if not extrapolated and leverage > model.max_leverage * (1 + 1e-9):
        extrapolated = True
        warnings.warn(
            "This combination of features is unlike any training machine, "
            "although each one is in range: the prediction is an extrapolation.",
            stacklevel=2,
        )
    noise = model.rel_iqr
    if noise is None:
        warnings.warn(
            "The run-to-run noise is unknown (one repetition per machine): "
            "the range covers only the validation error.",
            stacklevel=2,
        )
        noise = 0.0
    value = math.exp(log_value)
    spread = math.exp(model.max_log_error + math.log1p(noise))
    return Prediction(value, value / spread, value * spread, model.unit, extrapolated)


def loo_predictions(
    machines: pd.DataFrame,
    targets: pd.DataFrame,
    target: str,
    features: Sequence[str],
) -> pd.DataFrame:
    """Every held-out prediction behind ``evaluate`` for one target.

    One row per machine and method: ``actual``, ``predicted``, ``pct_error``.
    """
    features = list(features)
    return _loo(_table(machines, targets, target, features), features)


def evaluate(
    machines: pd.DataFrame,
    targets: pd.DataFrame,
    features: Sequence[str],
    targets_filter: str | None = None,
) -> pd.DataFrame:
    """Leave-one-machine-out errors of the model and both baselines.

    One row per target and method. Targets that cannot be fitted get one
    ``skipped`` row with the reason in ``note``.
    """
    features = list(features)
    _check_features(features)
    names = sorted(targets["target"].unique())
    if targets_filter:
        names = [name for name in names if targets_filter in name]
    rows: list[dict[str, Any]] = []
    for name in names:
        count = int((targets["target"] == name).sum())
        try:
            table = _table(machines, targets, name, features)
        except PredictionError as exc:
            rows.append(
                {
                    "target": name,
                    "method": "skipped",
                    "machines": count,
                    "note": str(exc),
                }
            )
            continue
        errors = _loo(table, features).groupby("method")["pct_error"]
        medians = errors.apply(lambda e: e.abs().median())
        maxima = errors.apply(lambda e: e.abs().max())
        wins = bool(medians["model"] < min(medians["mean"], medians["nearest"]))
        rows.extend(
            {
                "target": name,
                "method": method,
                "machines": count,
                "median_abs_pct_error": float(medians[method]),
                "max_abs_pct_error": float(maxima[method]),
                "beats_baselines": wins if method == "model" else None,
                "note": "",
            }
            for method in METHODS
        )
    return pd.DataFrame(rows, columns=EVALUATE_COLUMNS)


def _table(
    machines: pd.DataFrame, targets: pd.DataFrame, target: str, features: list[str]
) -> pd.DataFrame:
    """The target's rows joined to the machines' features, checked for fitting."""
    _check_features(features)
    rows = targets[targets["target"] == target]
    if rows.empty:
        similar = sorted(t for t in targets["target"].unique() if target in t)[:5]
        hint = f"; similar: {', '.join(similar)}" if similar else ""
        raise PredictionError(f"Unknown target '{target}'{hint}.")
    table = rows.merge(machines[["machine", *features]], on="machine", how="left")
    needed = len(features) + 2
    if len(table) < needed:
        raise PredictionError(
            f"'{target}' was measured on {len(table)} machine(s); "
            f"{len(features)} feature(s) need at least {needed}."
        )
    for feature in features:
        missing = table.loc[table[feature].isna(), "machine"].tolist()
        if missing:
            raise PredictionError(
                f"Feature '{feature}' is missing on {', '.join(missing)}."
            )
        if feature not in BINARY_FEATURES:
            bad = table.loc[table[feature] <= 0, "machine"].tolist()
            if bad:
                raise PredictionError(
                    f"Feature '{feature}' is not positive on {', '.join(bad)}."
                )
        if table[feature].nunique() < 2:
            raise PredictionError(
                f"Feature '{feature}' has the same value on every machine, "
                "so it cannot explain differences between them."
            )
    bad = table.loc[table["median"] <= 0, "machine"].tolist()
    if bad:
        raise PredictionError(
            f"'{target}' is not positive on {', '.join(bad)}; "
            "a log model needs positive values."
        )
    if np.linalg.matrix_rank(_design(table, features)) < len(features) + 1:
        raise PredictionError(
            f"Features {', '.join(features)} are collinear on these machines "
            "(one follows from the others), so their effects cannot be told "
            "apart; drop one."
        )
    return table.reset_index(drop=True)


def _check_features(features: list[str]) -> None:
    if not features:
        raise PredictionError("Pick at least one feature.")
    unknown = [f for f in features if f not in FEATURES]
    if unknown:
        raise PredictionError(
            f"Unknown feature '{unknown[0]}'; available: {', '.join(FEATURES)}."
        )


def _leverage(rows: np.ndarray, xtx_inv: np.ndarray) -> np.ndarray:
    """How far each row lies from the training machines, in the model's terms."""
    return np.einsum("ij,jk,ik->i", rows, xtx_inv, rows)


def _design(table: pd.DataFrame, features: list[str]) -> np.ndarray:
    columns = [
        table[f].to_numpy(float)
        if f in BINARY_FEATURES
        else np.log(table[f].to_numpy(float))
        for f in features
    ]
    return np.column_stack([np.ones(len(table)), *columns])


def _solve(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    return np.linalg.lstsq(x, y, rcond=None)[0]


def _loo(table: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    """Predict each machine from the others with the model and both baselines."""
    y = np.log(table["median"].to_numpy(float))
    z = _design(table, features)[:, 1:]
    rows = []
    for i in range(len(table)):
        rest = np.arange(len(table)) != i
        # Centred on the fold, a feature constant on the rest gets coefficient
        # 0 from lstsq, so the model falls back to the fold's mean.
        x = np.column_stack([np.ones(len(table)), z - z[rest].mean(axis=0)])
        sd = z[rest].std(axis=0)
        use = sd > 0
        # ponytail: with every feature constant on the rest, nearest is the first one
        distance = (((z[rest][:, use] - z[i, use]) / sd[use]) ** 2).sum(axis=1)
        guesses = {
            "model": float(x[i] @ _solve(x[rest], y[rest])),
            "mean": float(y[rest].mean()),
            "nearest": float(y[rest][int(np.argmin(distance))]),
        }
        actual = math.exp(y[i])
        for method, log_guess in guesses.items():
            predicted = math.exp(log_guess)
            rows.append(
                {
                    "machine": table["machine"].iat[i],
                    "method": method,
                    "actual": actual,
                    "predicted": predicted,
                    "pct_error": 100 * (predicted - actual) / actual,
                }
            )
    return pd.DataFrame(rows)


def _unit(table: pd.DataFrame) -> str:
    unit = table["unit"].dropna()
    return str(unit.iloc[0]) if not unit.empty else ""
