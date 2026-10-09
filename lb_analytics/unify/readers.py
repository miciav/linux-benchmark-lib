"""Turn one declared dataset file into rows of a unified table."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from lb_analytics.unify.report import LoadReport
from lb_common.api import DatasetDescriptor, plan_wide

RESULTS_COLUMNS = [
    "run_id",
    "host",
    "workload",
    "plugin",
    "repetition",
    "dataset",
    "metric",
    "value",
    "unit",
]
SAMPLES_COLUMNS = [
    "run_id",
    "host",
    "workload",
    "repetition",
    "collector",
    "timestamp",
    "metric",
    "value",
]
HOST_INFO_COLUMNS = ["run_id", "host", "category", "name", "value"]


@dataclass(frozen=True)
class SourceContext:
    run_id: str
    host: str
    workload: str | None
    plugin: str | None


def read_dataset(
    descriptor: DatasetDescriptor, path: Path, ctx: SourceContext, report: LoadReport
) -> pd.DataFrame | None:
    """Read one file of ``descriptor`` into its target table's shape.

    Any problem with the file becomes a report error for this dataset only: a
    localized fault never stops the rest of the experiment from loading.
    """
    source = str(path)
    try:
        # Keys are identities, not quantities: "5" must not become "5.0".
        keys_as_text = dict.fromkeys(descriptor.keys, "string")
        frame = pd.read_csv(path, dtype=keys_as_text)
        if descriptor.target_table == "host_info":
            return _host_info(descriptor, frame, ctx)
        if descriptor.shape == "timeseries":
            return _timeseries(descriptor, frame, ctx)
        long = (
            _wide(descriptor, frame, source, report)
            if descriptor.shape == "wide"
            else _long(descriptor, frame)
        )
        if long is None:
            return None
        return _finish_results(descriptor, long, ctx, source, report)
    except Exception as exc:
        report.error(source, f"{descriptor.name}: {exc}")
        return None


def _numeric(
    series: pd.Series, column: str, source: str, report: LoadReport
) -> pd.Series | None:
    values = pd.to_numeric(series, errors="coerce")
    bad = int((values.isna() & series.notna()).sum())
    if bad:
        report.error(source, f"column {column}: {bad} non-numeric values")
        return None
    return values.astype("float64")


def _wide(
    d: DatasetDescriptor, frame: pd.DataFrame, source: str, report: LoadReport
) -> pd.DataFrame | None:
    plan = plan_wide(d, list(frame.columns))
    for spec in plan.unmatched_specs:
        report.warn(source, f"{d.name}: metric {spec!r} matched no column")
    if plan.ignored:
        report.ignored_columns[source] = plan.ignored
    keys = [k for k in dict.fromkeys((*d.keys, "repetition")) if k in frame.columns]
    pieces = []
    for mc in plan.metrics:
        values = _numeric(frame[mc.column], mc.column, source, report)
        if values is None:
            return None
        piece = frame[keys].copy()
        piece["metric"] = mc.metric
        piece["value"] = values
        piece["unit"] = (
            frame[mc.unit_column] if mc.unit_column in frame.columns else mc.unit
        )
        for dim, value in mc.dims.items():
            piece[f"dim_{dim}"] = value
        pieces.append(piece)
    if not pieces:
        return pd.DataFrame(columns=[*keys, "metric", "value", "unit"])
    return pd.concat(pieces, ignore_index=True)


def _long(d: DatasetDescriptor, frame: pd.DataFrame) -> pd.DataFrame:
    keys = [k for k in dict.fromkeys((*d.keys, "repetition")) if k in frame.columns]
    if d.value_columns:
        pieces = []
        for vc in d.value_columns:
            piece = frame[keys].copy()
            piece["metric"] = vc.column
            piece["value"] = frame[vc.column]
            piece["unit"] = vc.unit
            pieces.append(piece)
        return pd.concat(pieces, ignore_index=True)
    assert d.metric_column is not None and d.value_column is not None
    piece = frame[keys].copy()
    piece["metric"] = frame[d.metric_column].astype("string")
    piece["value"] = frame[d.value_column]
    piece["unit"] = frame[d.unit_column] if d.unit_column else d.unit
    return piece


def _finish_results(
    d: DatasetDescriptor,
    frame: pd.DataFrame,
    ctx: SourceContext,
    source: str,
    report: LoadReport,
) -> pd.DataFrame | None:
    values = _numeric(frame["value"], "value", source, report)
    if values is None:
        return None
    frame = frame.assign(value=values)
    for key, value in d.fixed.items():
        frame[key] = value
    missing = int(frame["value"].isna().sum())
    if missing:
        report.missing_values[source] = report.missing_values.get(source, 0) + missing
    frame = frame[frame["value"].notna()]
    renames = {k: f"dim_{k}" for k in (*d.keys, *d.fixed) if k != "repetition"}
    frame = frame.rename(columns=renames)
    frame = frame.assign(
        run_id=ctx.run_id,
        host=ctx.host,
        workload=ctx.workload,
        plugin=ctx.plugin,
        dataset=d.name,
    )
    if "repetition" not in frame.columns:
        frame["repetition"] = pd.NA
    dims = sorted(c for c in frame.columns if c.startswith("dim_"))
    out = frame[RESULTS_COLUMNS + dims].copy()
    out["unit"] = out["unit"].astype("string")
    out["metric"] = out["metric"].astype("string")
    for dim in dims:
        out[dim] = out[dim].astype("string")
    out["repetition"] = pd.to_numeric(out["repetition"]).astype("Int64")
    return out.reset_index(drop=True)


def _timeseries(
    d: DatasetDescriptor, frame: pd.DataFrame, ctx: SourceContext
) -> pd.DataFrame:
    assert d.time_column is not None
    excluded = [re.compile(p) for p in d.exclude]
    metrics = [
        c
        for c in frame.columns
        if c != d.time_column
        and c not in d.keys
        and not any(p.fullmatch(c) for p in excluded)
        and pd.api.types.is_numeric_dtype(frame[c])
    ]
    melted = frame[[d.time_column, *metrics]].melt(
        id_vars=[d.time_column], var_name="metric", value_name="value"
    )
    melted = melted.rename(columns={d.time_column: "timestamp"})
    melted["timestamp"] = pd.to_datetime(melted["timestamp"], errors="coerce")
    melted = melted.assign(
        run_id=ctx.run_id,
        host=ctx.host,
        workload=ctx.workload,
        collector=str(d.fixed.get("collector", d.name)),
    )
    melted["repetition"] = d.fixed.get("repetition", pd.NA)
    out = melted[SAMPLES_COLUMNS].copy()
    out["repetition"] = pd.to_numeric(out["repetition"]).astype("Int64")
    out["value"] = out["value"].astype("float64")
    out["metric"] = out["metric"].astype("string")
    return out[out["value"].notna()].reset_index(drop=True)


def _host_info(
    d: DatasetDescriptor, frame: pd.DataFrame, ctx: SourceContext
) -> pd.DataFrame:
    # Assumes keys are exactly category, name (the runner's system_info dataset).
    assert d.value_column is not None
    out = frame[[*d.keys, d.value_column]].astype("string")
    out = out.rename(columns={d.value_column: "value"})
    out.insert(0, "host", ctx.host)
    out.insert(0, "run_id", ctx.run_id)
    return out[HOST_INFO_COLUMNS].reset_index(drop=True)
