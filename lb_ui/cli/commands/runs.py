from __future__ import annotations

from pathlib import Path

import typer

from lb_app.api import RunCatalogService, UnificationError
from lb_ui.flows.unification import (
    build_unification_service,
    is_interactive,
    run_unification_flow,
    show_summary,
    write_and_report,
)
from lb_ui.tui.system.models import PickItem, TableModel
from lb_ui.wiring.dependencies import UIContext


def _show_run_details(
    ctx: UIContext,
    run_id: str,
    catalog: RunCatalogService,
) -> None:
    run = catalog.get_run(run_id)
    if not run:
        ctx.ui.present.error(f"Run '{run_id}' not found")
        return
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
    ctx.ui.tables.show(
        TableModel(title="Run Details", columns=["Field", "Value"], rows=rows)
    )


def create_runs_app(ctx: UIContext) -> typer.Typer:
    """Build the runs Typer app (list/show/analyze)."""
    app = typer.Typer(help="Inspect past benchmark runs.", no_args_is_help=True)

    @app.command("list")
    def runs_list(
        root: Path | None = typer.Option(
            None,
            "--root",
            "-r",
            help="Root directory containing benchmark_results run folders.",
        ),
        config: Path | None = typer.Option(
            None,
            "--config",
            "-c",
            help="Config file to infer output/report/export roots.",
        ),
        interactive: bool = typer.Option(
            True,
            "--interactive/--no-interactive",
            help="After listing, offer interactive run navigation (requires TTY).",
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
        rows: list[list[str]] = []
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

        # Interactive navigation — only when TTY is available
        if not interactive or ctx.headless:
            return
        from lb_ui.tui.core.capabilities import is_tty_available

        if not is_tty_available():
            return

        run_items = [
            PickItem(
                id=run.run_id,
                title=run.run_id,
                description=(
                    f"Created: {run.created_at.isoformat() if run.created_at else '-'}"
                    f"  Hosts: {', '.join(run.hosts) if run.hosts else '-'}"
                ),
            )
            for run in runs
        ]
        selected = ctx.ui.picker.pick_one(run_items, title="Select a run to inspect")
        if selected is None:
            return

        actions = [
            PickItem(id="show", title="Show details"),
            PickItem(id="analyze", title="Analyze"),
        ]
        action = ctx.ui.picker.pick_one(actions, title=f"Action for {selected.id}")
        if action is None:
            return

        if action.id == "show":
            _show_run_details(ctx, selected.id, catalog)
        elif action.id == "analyze":
            ctx.ui.present.info(f"Run: lb runs analyze {selected.id}")

    @app.command("show")
    def runs_show(
        run_id: str = typer.Argument(..., help="Run identifier (folder name)."),
        root: Path | None = typer.Option(
            None,
            "--root",
            "-r",
            help="Root directory containing benchmark_results run folders.",
        ),
        config: Path | None = typer.Option(
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
        _show_run_details(ctx, run_id, catalog)

    @app.command("analyze")
    def analyze(
        experiment: str | None = typer.Option(
            None, "--experiment", "-e", help="Experiment to unify."
        ),
        folder: bool = typer.Option(
            False,
            "--folder",
            help="Unify every run of the output folder as one experiment.",
        ),
        root: Path | None = typer.Option(
            None,
            "--root",
            "-r",
            help="Root directory containing benchmark_results run folders.",
        ),
        workload: list[str] | None = typer.Option(
            None,
            "--workload",
            "-w",
            help="Workload(s) to keep (repeatable). Default: all.",
        ),
        host: list[str] | None = typer.Option(
            None,
            "--host",
            "-H",
            help="Host(s) to keep (repeatable). Default: all.",
        ),
        config: Path | None = typer.Option(
            None,
            "--config",
            "-c",
            help="Config file to infer output/report/export roots.",
        ),
    ) -> None:
        """Unify an experiment's datasets into Parquet tables."""
        if experiment is not None and folder:
            ctx.ui.present.error("Use --experiment or --folder, not both.")
            raise typer.Exit(1)
        cfg, resolved, _ = ctx.config_service.load_for_read(config)
        service = build_unification_service(cfg, root, resolved)
        try:
            if experiment is None and not folder:
                if not is_interactive(ctx):
                    ctx.ui.present.error(
                        "Choose what to unify: --experiment ID or --folder."
                    )
                    raise typer.Exit(1)
                run_unification_flow(ctx, service)
                return
            preview = service.prepare(
                service.find(experiment), host or (), workload or ()
            )
            show_summary(ctx, preview)
            write_and_report(ctx, service, preview)
        except UnificationError as exc:
            ctx.ui.present.error(str(exc))
            raise typer.Exit(1) from exc

    return app
