"""Pick an experiment, review what its unification produces, write it."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from rich.table import Table

from lb_app.api import (
    BenchmarkConfig,
    ExperimentInfo,
    RunCatalogService,
    UnificationError,
    UnificationPreview,
    UnificationService,
)
from lb_ui.tui.core.capabilities import is_tty_available
from lb_ui.tui.system.models import PickItem, TableModel
from lb_ui.wiring.dependencies import UIContext


def build_unification_service(
    cfg: BenchmarkConfig, root: Path | None = None, config_path: Path | None = None
) -> UnificationService:
    catalog = RunCatalogService(
        root or cfg.output_dir,
        report_dir=cfg.report_dir,
        data_export_dir=cfg.data_export_dir,
    )
    return UnificationService(catalog, cfg.data_export_dir, config_path=config_path)


def is_interactive(ctx: UIContext) -> bool:
    return not ctx.headless and is_tty_available()


def run_unification_flow(
    ctx: UIContext,
    service: UnificationService,
    experiment: ExperimentInfo | None = None,
) -> list[Path] | None:
    """Pick (unless preselected) → summary → unify, filter or cancel."""
    if experiment is None:
        experiment = _pick(ctx, service)
        if experiment is None:
            return None
    hosts: tuple[str, ...] = ()
    workloads: tuple[str, ...] = ()
    while True:
        with ctx.ui.progress.status(f"Loading {experiment.id}"):
            preview = service.prepare(experiment, hosts, workloads)
        show_summary(ctx, preview)
        actions = [] if preview.is_empty else [PickItem(id="unify", title="Unify")]
        actions += [
            PickItem(id="filters", title="Filters (hosts, workloads)"),
            PickItem(id="cancel", title="Cancel"),
        ]
        action = ctx.ui.picker.pick_one(actions, title=f"Unify {experiment.id}?")
        if action is None or action.id == "cancel":
            return None
        if action.id == "unify":
            return write_and_report(ctx, service, preview)
        hosts = _pick_subset(ctx, "hosts", experiment.hosts, preview.hosts)
        workloads = _pick_subset(
            ctx, "workloads", experiment.workloads, preview.workloads
        )


def show_summary(ctx: UIContext, preview: UnificationPreview) -> None:
    ctx.ui.tables.show(
        TableModel(
            title=f"Unification of {preview.experiment.id}",
            columns=["Field", "Value"],
            rows=[list(row) for row in preview.summary_rows()],
        )
    )


def write_and_report(
    ctx: UIContext, service: UnificationService, preview: UnificationPreview
) -> list[Path]:
    with ctx.ui.progress.status("Writing Parquet tables"):
        paths = service.write(preview)
    counts = preview.row_counts
    ctx.ui.tables.show(
        TableModel(
            title=f"Written to {preview.out_dir}",
            columns=["File", "Rows"],
            rows=[[p.name, str(counts.get(p.stem, "-"))] for p in paths],
        )
    )
    errors = preview.data.report.errors
    if errors:
        ctx.ui.present.warning(
            f"{len(errors)} load error(s): the data is partial, "
            "details in load_report.json"
        )
    ctx.ui.present.success(f"Unified {preview.experiment.id} into {preview.out_dir}")
    ctx.ui.present.info(f"Equivalent command: {preview.command}")
    return paths


def _pick(ctx: UIContext, service: UnificationService) -> ExperimentInfo | None:
    targets = service.list_targets()
    if not targets:
        raise UnificationError(f"No runs in {service.output_dir}")
    items = [_target_item(target) for target in targets]
    chosen = ctx.ui.picker.pick_one(items, title="Select what to unify")
    return chosen.payload if chosen else None


def _target_item(target: ExperimentInfo) -> PickItem:
    last = (
        target.last_created.strftime("%Y-%m-%d %H:%M") if target.last_created else "-"
    )
    title = f"Folder {target.id} (all runs)" if target.kind == "folder" else target.id
    return PickItem(
        id=f"{target.kind}:{target.id}",
        title=title,
        description=f"{len(target.runs)} run(s), last {last}",
        search_blob=" ".join([target.id, *target.hosts, *target.workloads]),
        preview=_runs_table(target),
        payload=target,
    )


def _runs_table(target: ExperimentInfo) -> Table:
    table = Table(title=target.id)
    for column in ("Run", "Created", "Hosts", "Workloads"):
        table.add_column(column)
    for run in target.runs:
        created = run.created_at.strftime("%Y-%m-%d %H:%M") if run.created_at else "-"
        table.add_row(
            run.run_id, created, ", ".join(run.hosts), ", ".join(run.workloads)
        )
    return table


def _pick_subset(
    ctx: UIContext,
    label: str,
    available: Sequence[str],
    current: tuple[str, ...],
) -> tuple[str, ...]:
    """Pick-many starting from the current filter; picking nothing keeps it."""
    items = [
        PickItem(id=name, title=name, selected=not current or name in current)
        for name in available
    ]
    chosen = ctx.ui.picker.pick_many(items, title=f"Select {label} to unify")
    return tuple(item.id for item in chosen) if chosen else current


def unify_after_run(
    ctx: UIContext,
    cfg: BenchmarkConfig,
    journal_path: Path,
    config_path: Path | None,
    *,
    forced: bool,
) -> bool:
    """End of ``lb run``: unify the run's experiment if asked to, or if agreed.

    Returns False only when a unification was attempted and failed.
    """
    if not forced and not is_interactive(ctx):
        return True
    try:
        metadata = json.loads(journal_path.read_text()).get("metadata") or {}
    except (OSError, ValueError, AttributeError):
        metadata = {}
    experiment_id = metadata.get("experiment_id")
    if not experiment_id:
        ctx.ui.present.warning(
            "The run's journal has no experiment id; nothing to unify."
        )
        return True
    if not forced and not ctx.ui.form.confirm(
        f"Unify experiment {experiment_id} now?", default=False
    ):
        return True
    service = build_unification_service(cfg, None, config_path)
    try:
        preview = service.prepare(service.find(experiment_id))
        show_summary(ctx, preview)
        write_and_report(ctx, service, preview)
    except UnificationError as exc:
        ctx.ui.present.error(str(exc))
        return False
    return True
