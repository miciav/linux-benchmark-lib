"""Find every manifest of a set of runs and build the unified tables."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from lb_analytics.unify.experiment import ExperimentData
from lb_analytics.unify.readers import (
    HOST_INFO_COLUMNS,
    RESULTS_COLUMNS,
    SAMPLES_COLUMNS,
    SourceContext,
    read_dataset,
)
from lb_analytics.unify.report import LoadReport
from lb_common.api import MANIFEST_FILENAME, DatasetManifest, RunInfo, read_manifest

RUNS_COLUMNS = ["run_id", "experiment_id", "created_at", "config_hash", "repetitions"]
REPETITION_COLUMNS = [
    "run_id",
    "host",
    "workload",
    "plugin",
    "repetition",
    "success",
    "start_time",
    "end_time",
    "duration_seconds",
]


def load_experiment(runs: Sequence[RunInfo]) -> ExperimentData:
    """Load every declared dataset of ``runs`` into unified tables."""
    report = LoadReport()
    frames: dict[str, list[pd.DataFrame]] = {
        "results": [],
        "samples": [],
        "host_info": [],
    }
    run_rows: list[dict[str, Any]] = []
    repetition_rows: list[dict[str, Any]] = []
    for run in runs:
        root = run.output_root
        run_rows.append(_run_row(run, report))
        for manifest_dir in _manifest_dirs(root):
            try:
                manifest = read_manifest(manifest_dir)
            except Exception as exc:
                report.error(str(manifest_dir), f"invalid {MANIFEST_FILENAME}: {exc}")
                continue
            ctx = SourceContext(
                run.run_id,
                _host_of(root, manifest_dir, manifest),
                manifest.workload,
                manifest.plugin,
            )
            _load_manifest(manifest, manifest_dir, ctx, frames, report)
            repetition_rows.extend(_repetitions(manifest, manifest_dir, ctx, report))
        _report_unmanifested(root, report)
    return ExperimentData(
        runs=_runs_frame(run_rows),
        host_info=_concat(frames["host_info"], HOST_INFO_COLUMNS),
        repetitions=pd.DataFrame(repetition_rows, columns=REPETITION_COLUMNS),
        results=_concat(frames["results"], RESULTS_COLUMNS),
        samples=_concat(frames["samples"], SAMPLES_COLUMNS),
        report=report,
    )


def _manifest_dirs(root: Path) -> list[Path]:
    found = [
        *root.glob(MANIFEST_FILENAME),
        *root.glob(f"*/{MANIFEST_FILENAME}"),
        *root.glob(f"*/*/{MANIFEST_FILENAME}"),
    ]
    return sorted(p.parent for p in found)


def _host_of(root: Path, manifest_dir: Path, manifest: DatasetManifest) -> str:
    host_dir = manifest_dir.parent if manifest.workload else manifest_dir
    return "localhost" if host_dir == root else host_dir.name


def _load_manifest(
    manifest: DatasetManifest,
    manifest_dir: Path,
    ctx: SourceContext,
    frames: dict[str, list[pd.DataFrame]],
    report: LoadReport,
) -> None:
    for descriptor in manifest.datasets:
        if descriptor.target_table == "ignore":
            continue
        files = sorted(manifest_dir.glob(descriptor.path))
        if not files:
            report.error(
                str(manifest_dir),
                f"{descriptor.name}: declared file {descriptor.path!r} not found",
            )
            continue
        for path in files:
            frame = read_dataset(descriptor, path, ctx, report)
            if frame is not None:
                frames[descriptor.target_table].append(frame)
                report.files_read.append(str(path))
    _report_undeclared(manifest, manifest_dir, report)


def _report_undeclared(
    manifest: DatasetManifest, manifest_dir: Path, report: LoadReport
) -> None:
    declared = {p for d in manifest.datasets for p in manifest_dir.glob(d.path)}
    # A host manifest owns only its own directory; workload ones own their tree.
    candidates = (
        manifest_dir.rglob("*.csv") if manifest.workload else manifest_dir.glob("*.csv")
    )
    report.undeclared_files.extend(
        str(p) for p in sorted(candidates) if p not in declared
    )


def _report_unmanifested(root: Path, report: LoadReport) -> None:
    results_files = [*root.glob("*/*_results.json"), *root.glob("*/*/*_results.json")]
    for results_file in sorted(results_files):
        if not (results_file.parent / MANIFEST_FILENAME).exists():
            report.not_loadable.append(str(results_file.parent))


def _repetitions(
    manifest: DatasetManifest,
    manifest_dir: Path,
    ctx: SourceContext,
    report: LoadReport,
) -> list[dict[str, Any]]:
    if not manifest.repetitions:
        return []
    path = manifest_dir / manifest.repetitions
    try:
        entries = json.loads(path.read_text())
    except Exception as exc:
        report.error(str(path), f"cannot read repetitions: {exc}")
        return []
    rows = []
    for entry in entries:
        row = {
            "run_id": ctx.run_id,
            "host": ctx.host,
            "workload": ctx.workload,
            "plugin": ctx.plugin,
            **{k: entry.get(k) for k in REPETITION_COLUMNS[4:]},
        }
        rows.append(row)
        if row["success"] is False:
            report.failed_repetitions.append(
                {k: row[k] for k in ("run_id", "host", "workload", "repetition")}
            )
    return rows


def _run_row(run: RunInfo, report: LoadReport) -> dict[str, Any]:
    journal = run.output_root / "run_journal.json"
    metadata: dict[str, Any] = {}
    try:
        metadata = json.loads(journal.read_text()).get("metadata", {})
    except Exception as exc:
        report.warn(str(run.output_root), f"run_journal.json unreadable: {exc}")
    return {
        "run_id": run.run_id,
        "experiment_id": metadata.get("experiment_id"),
        "created_at": metadata.get("created_at"),
        "config_hash": metadata.get("config_hash"),
        "repetitions": metadata.get("repetitions"),
    }


def _runs_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=RUNS_COLUMNS)
    frame["created_at"] = pd.to_datetime(frame["created_at"], errors="coerce")
    return frame


def _concat(frames: list[pd.DataFrame], columns: list[str]) -> pd.DataFrame:
    if not frames:
        return pd.DataFrame(columns=columns)
    out = pd.concat(frames, ignore_index=True)
    # Frames without a given dimension leave it missing: keep it a string column
    # of real nulls rather than letting concat fall back to object/NaN.
    for column in out.columns:
        if column.startswith("dim_"):
            out[column] = out[column].astype("string")
    return out
