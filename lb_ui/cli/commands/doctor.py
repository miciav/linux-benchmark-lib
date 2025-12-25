from __future__ import annotations

import typer

from lb_app.api import DoctorService
from lb_ui.presenters.doctor import render_doctor_report


def create_doctor_app(doctor_service: DoctorService, ui) -> typer.Typer:
    """Build the doctor Typer app, wired to the given service and UI."""
    app = typer.Typer(help="Check environment health and prerequisites.", no_args_is_help=False)

    @app.callback(invoke_without_command=True)
    def doctor_root(ctx: typer.Context) -> None:
        if ctx.invoked_subcommand is None:
            report = doctor_service.check_all()
            ok = render_doctor_report(ui, report)
            if not ok:
                raise typer.Exit(1)

    @app.command("all")
    def doctor_all() -> None:
        """Run all checks."""
        report = doctor_service.check_all()
        ok = render_doctor_report(ui, report)
        if not ok:
            raise typer.Exit(1)

    @app.command("controller")
    def doctor_controller() -> None:
        """Check controller prerequisites (Ansible, Python deps)."""
        report = doctor_service.check_controller()
        ok = render_doctor_report(ui, report)
        if not ok:
            raise typer.Exit(1)

    @app.command("local")
    def doctor_local() -> None:
        """Check local workload tools (stress-ng, fio, etc)."""
        report = doctor_service.check_local_tools()
        ok = render_doctor_report(ui, report)
        if not ok:
            raise typer.Exit(1)

    @app.command("multipass")
    def doctor_multipass() -> None:
        """Check Multipass installation."""
        report = doctor_service.check_multipass()
        ok = render_doctor_report(ui, report)
        if not ok:
            raise typer.Exit(1)

    return app
