"""
Command-line interface for linux-benchmark-lib.

Exposes quick commands to inspect plugins/hosts and run benchmarks via provisioned environments (remote, Docker, Multipass).
"""

from __future__ import annotations

import os
import subprocess
from typing import Optional

import typer

from pathlib import Path
from lb_ui.ui.system.models import PickItem

# Command modules
from lb_ui.commands.config import create_config_app
from lb_ui.commands.doctor import create_doctor_app
from lb_ui.commands.plugin import create_plugin_app
from lb_ui.commands.runs import create_runs_app, register_analyze_command
from lb_ui.commands.test import create_test_app
from lb_ui.commands.run import register_run_command

from lb_ui.dependencies import create_ui, create_services, load_dev_mode, configure_logging

# Initialize UI and services via dependencies
_CLI_ROOT = Path(__file__).resolve().parent.parent
DEV_MODE = load_dev_mode(_CLI_ROOT)
TEST_CLI_ENABLED = bool(os.environ.get("LB_ENABLE_TEST_CLI")) or DEV_MODE

ui, ui_adapter = create_ui()
config_service, doctor_service, test_service, analytics_service, app_client = create_services()
doctor_app = create_doctor_app(doctor_service, ui)
runs_app = create_runs_app(lambda: config_service, ui)
config_app = create_config_app(config_service, ui)
test_app = create_test_app(test_service, doctor_service, ui)
plugin_app = create_plugin_app(config_service, ui)

app = typer.Typer(help="Run linux-benchmark workloads on provisioned hosts (remote, Docker, Multipass).", no_args_is_help=True)


@app.callback(invoke_without_command=True)
def entry(
    ctx: typer.Context,
    headless: bool = typer.Option(
        False,
        "--headless",
        help="Force headless output (useful in CI).",
    ),
    config: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Config file to load when launching the TUI.",
    ),
) -> None:
    """Global entry point handling interactive vs headless modes."""
    global ui, ui_adapter
    configure_logging(force=True)
    if headless:
        from lb_ui.ui.system.headless import HeadlessUI
        ui = HeadlessUI()
        ui_adapter = TUIAdapter(ui)
        # Re-inject if necessary, but services now mostly return data or use ui_adapter passed in methods (RunService)

    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()




register_analyze_command(app, lambda: config_service, lambda: analytics_service, ui)


app.add_typer(config_app, name="config")
app.add_typer(doctor_app, name="doctor")
app.add_typer(plugin_app, name="plugin")
app.add_typer(runs_app, name="runs")
if TEST_CLI_ENABLED:
    app.add_typer(test_app, name="test")
else:

    @app.command("test")
    def _test_disabled() -> None:
        """Hide test helpers when not installed in dev mode."""
        ui.present.error(
            "`lb test` is available only in dev installs. "
            "Run `LB_ENABLE_TEST_CLI=1 lb test ...` or create .lb_dev_cli to override."
        )
        raise typer.Exit(1)


register_run_command(
    app=app,
    app_client=app_client,
    config_service_provider=lambda: config_service,
    ui=ui,
    ui_adapter=ui_adapter,
    dev_mode=DEV_MODE,
)






@app.command("plugins", hidden=True)
def list_plugins() -> None:
    """Compatibility alias for plugin list."""
    ui.present.info("Use `lb plugin list`.") 


def main() -> None:
    """Console script entrypoint (Typer app)."""
    app()


if __name__ == "__main__":
    main()
