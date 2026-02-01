from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from lb_ui.wiring.dependencies import UIContext
from lb_ui.presenters.doctor import render_doctor_report


def create_doctor_app(ctx: UIContext) -> typer.Typer:
    """Build the doctor Typer app, wired to the given context."""
    app = typer.Typer(help="Check environment health and prerequisites.", no_args_is_help=False)

    @app.callback(invoke_without_command=True)
    def doctor_root(typer_ctx: typer.Context) -> None:
        if typer_ctx.invoked_subcommand is None:
            report = ctx.doctor_service.check_all()
            ok = render_doctor_report(ctx.ui, report)
            if not ok:
                raise typer.Exit(1)

    @app.command("all")
    def doctor_all() -> None:
        """Run all checks."""
        report = ctx.doctor_service.check_all()
        ok = render_doctor_report(ctx.ui, report)
        if not ok:
            raise typer.Exit(1)

    @app.command("controller")
    def doctor_controller() -> None:
        """Check controller prerequisites (Ansible, Python deps)."""
        report = ctx.doctor_service.check_controller()
        ok = render_doctor_report(ctx.ui, report)
        if not ok:
            raise typer.Exit(1)

    @app.command("local")
    def doctor_local() -> None:
        """Check local workload tools (stress-ng, fio, etc)."""
        report = ctx.doctor_service.check_local_tools()
        ok = render_doctor_report(ctx.ui, report)
        if not ok:
            raise typer.Exit(1)

    @app.command("multipass")
    def doctor_multipass() -> None:
        """Check Multipass installation."""
        report = ctx.doctor_service.check_multipass()
        ok = render_doctor_report(ctx.ui, report)
        if not ok:
            raise typer.Exit(1)

    @app.command("hosts")
    def doctor_hosts(
        config: Optional[Path] = typer.Option(
            None,
            "--config",
            "-c",
            help="Config file to load; uses saved default or local benchmark_config.json when omitted.",
        ),
        timeout: int = typer.Option(
            10,
            "--timeout",
            "-t",
            help="Timeout in seconds for each host connection check.",
        ),
    ) -> None:
        """Check SSH connectivity to configured remote hosts."""
        cfg, resolved, stale = ctx.config_service.load_for_read(config)
        if stale:
            ctx.ui.present.warning(f"Saved default config not found: {stale}")
        if resolved:
            ctx.ui.present.info(f"Using config: {resolved}")
        else:
            ctx.ui.present.warning("No config file found; using built-in defaults.")

        report = ctx.doctor_service.check_remote_hosts(cfg, timeout_seconds=timeout)
        ok = render_doctor_report(ctx.ui, report)
        if not ok:
            raise typer.Exit(1)

    return app
