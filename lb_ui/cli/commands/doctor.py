from __future__ import annotations

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

    return app
