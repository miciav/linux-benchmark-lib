from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import typer

from lb_app.api import AnalyticsRequest, RunCatalogService
from lb_ui.tui.system.models import PickItem, TableModel


from lb_ui.wiring.dependencies import UIContext


def create_runs_app(ctx: UIContext) -> typer.Typer:
    """Build the runs Typer app (list/show)."""
    app = typer.Typer(help="Inspect past benchmark runs.", no_args_is_help=True)

    @app.command("list")
    def runs_list(
        root: Optional[Path] = typer.Option(
            None,
            "--root",
            "-r",
            help="Root directory containing benchmark_results run folders.",
        ),
        config: Optional[Path] = typer.Option(
            None,
            "--config",
            "-c",
            help="Config file to infer output/report/export roots.",
        ),
    ) -> None:
        """List available benchmark runs."""
        cfg, _, _ = ctx.config_service.load_for_read(config)
        output_root = root or cfg.output_dir
        catalog = RunCatalogService(
            output_dir=output_root,
            report_dir=cfg.report_dir,
            data_export_dir=cfg.data_export_dir,
        )
        runs = catalog.list_runs()
        if not runs:
            ctx.ui.present.warning(f"No runs found under {output_root}")
            return
        rows: List[List[str]] = []
        for run in runs:
            created = run.created_at.isoformat() if run.created_at else "-"
            hosts = ", ".join(run.hosts) if run.hosts else "-"
            workloads = ", ".join(run.workloads) if run.workloads else "-"
            rows.append([run.run_id, created, hosts, workloads])
        ctx.ui.tables.show(
            TableModel(
                title="Benchmark Runs",
                columns=["Run ID", "Created", "Hosts", "Workloads"],
                rows=rows,
            )
        )

    @app.command("show")
    def runs_show(
        run_id: str = typer.Argument(..., help="Run identifier (folder name)."),
        root: Optional[Path] = typer.Option(
            None,
            "--root",
            "-r",
            help="Root directory containing benchmark_results run folders.",
        ),
        config: Optional[Path] = typer.Option(
            None,
            "--config",
            "-c",
            help="Config file to infer output/report/export roots.",
        ),
    ) -> None:
        """Show details for a single run."""
        cfg, _, _ = ctx.config_service.load_for_read(config)
        output_root = root or cfg.output_dir
        catalog = RunCatalogService(
            output_dir=output_root,
            report_dir=cfg.report_dir,
            data_export_dir=cfg.data_export_dir,
        )
        run = catalog.get_run(run_id)
        if not run:
            ctx.ui.present.error(f"Run '{run_id}' not found under {output_root}")
            raise typer.Exit(1)
        rows = [
            ["Run ID", run.run_id],
            ["Output", str(run.output_root)],
            ["Reports", str(run.report_root or "-")],
            ["Exports", str(run.data_export_root or "-")],
            ["Created", run.created_at.isoformat() if run.created_at else "-"],
            ["Hosts", ", ".join(run.hosts) if run.hosts else "-"],
            ["Workloads", ", ".join(run.workloads) if run.workloads else "-"],
            ["Journal", str(run.journal_path or "-")],
        ]
        ctx.ui.tables.show(TableModel(title="Run Details", columns=["Field", "Value"], rows=rows))

    return app


def register_analyze_command(
    app: typer.Typer,
    ctx: UIContext,
) -> None:
    """Register the analyze command on the given Typer app."""

    @app.command("analyze")
    def analyze(
        run_id: Optional[str] = typer.Argument(
            None, help="Run identifier (folder name). If omitted, prompt to select."
        ),
        kind: Optional[str] = typer.Option(
            None,
            "--kind",
            "-k",
            help="Analytics kind to run (currently: aggregate).",
        ),
        root: Optional[Path] = typer.Option(
            None,
            "--root",
            "-r",
            help="Root directory containing benchmark_results run folders.",
        ),
        workload: Optional[List[str]] = typer.Option(
            None,
            "--workload",
            "-w",
            help="Workload(s) to analyze (repeatable). Default: all in run.",
        ),
        host: Optional[List[str]] = typer.Option(
            None,
            "--host",
            "-H",
            help="Host(s) to analyze (repeatable). Default: all in run.",
        ),
        config: Optional[Path] = typer.Option(
            None,
            "--config",
            "-c",
            help="Config file to infer output/report/export roots.",
        ),
    ) -> None:
        """Run analytics on an existing benchmark run."""
        cfg, _, _ = ctx.config_service.load_for_read(config)
        output_root = root or cfg.output_dir
        catalog = RunCatalogService(
            output_dir=output_root,
            report_dir=cfg.report_dir,
            data_export_dir=cfg.data_export_dir,
        )

        selected_run_id = run_id
        if selected_run_id is None:
            runs = catalog.list_runs()
            if not runs:
                ctx.ui.present.error(f"No runs found under {output_root}")
                raise typer.Exit(1)

            items = [PickItem(id=r.run_id, title=f"{r.run_id} ({r.created_at})") for r in runs]
            selection = ctx.ui.picker.pick_one(items, title="Select a benchmark run")
            selected_run_id = selection.id if selection else runs[0].run_id
            ctx.ui.present.info(f"Selected run: {selected_run_id}")

        run = catalog.get_run(selected_run_id)
        if not run:
            ctx.ui.present.error(f"Run '{selected_run_id}' not found under {output_root}")
            raise typer.Exit(1)

        selected_kind = kind
        if not selected_kind:
            k_items = [PickItem(id="aggregate", title="aggregate")]
            k_sel = ctx.ui.picker.pick_one(k_items, title="Select analytics type", query_hint="aggregate")
            selected_kind = k_sel.id if k_sel else "aggregate"

        if selected_kind != "aggregate":
            ctx.ui.present.error(f"Unsupported analytics kind: {selected_kind}")
            raise typer.Exit(1)

        selected_workloads = workload
        if selected_workloads is None:
            w_items = [PickItem(id=w, title=w) for w in list(run.workloads)]
            w_sel = ctx.ui.picker.pick_many(w_items, title="Select workloads to analyze")
            selected_workloads = sorted([s.id for s in w_sel]) if w_sel else None

        selected_hosts = host
        if selected_hosts is None:
            h_items = [PickItem(id=h, title=h) for h in list(run.hosts)]
            h_sel = ctx.ui.picker.pick_many(h_items, title="Select hosts to analyze")
            selected_hosts = sorted([s.id for s in h_sel]) if h_sel else None

        req = AnalyticsRequest(
            run=run,
            kind="aggregate",
            hosts=selected_hosts,
            workloads=selected_workloads,
        )
        with ctx.ui.progress.status(f"Running analytics '{selected_kind}' on {run.run_id}"):
            produced = ctx.analytics_service.run(req)
        if not produced:
            ctx.ui.present.warning("No analytics artifacts produced.")
            return
        rows = [[str(p)] for p in produced]
        ctx.ui.tables.show(TableModel(title="Analytics Artifacts", columns=["Path"], rows=rows))
        ctx.ui.present.success("Analytics completed.")
