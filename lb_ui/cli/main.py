"""
Command-line interface for linux-benchmark-lib.

Exposes quick commands to inspect plugins/hosts and run benchmarks via provisioned environments (remote, Docker, Multipass).
"""

from __future__ import annotations

import os
from typing import Optional

import typer

from pathlib import Path

# Command modules
from lb_ui.cli.commands.config import create_config_app
from lb_ui.cli.commands.doctor import create_doctor_app
from lb_ui.cli.commands.plugin import create_plugin_app
from lb_ui.cli.commands.runs import create_runs_app, register_analyze_command
from lb_ui.cli.commands.resume import register_resume_command
from lb_ui.cli.commands.test import create_test_app
from lb_ui.cli.commands.run import register_run_command

from lb_ui.wiring.dependencies import load_dev_mode, configure_logging, UIContext

# Initialize global context (lazy)
_CLI_ROOT = Path(__file__).resolve().parent.parent.parent
ctx_store = UIContext(dev_mode=load_dev_mode(_CLI_ROOT))

# Shortcuts for clarity in registration
def ui_provider(): return ctx_store.ui
def ui_adapter_provider(): return ctx_store.ui_adapter

doctor_app = create_doctor_app(ctx_store)
runs_app = create_runs_app(ctx_store)
config_app = create_config_app(ctx_store)
test_app = create_test_app(ctx_store)
plugin_app = create_plugin_app(ctx_store)

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
    configure_logging(force=True)
    ctx_store.headless = headless
    
    # If a specific config is provided, we might want to tell config_service 
    # but currently ConfigService reads from env or default targets.
    # The commands usually handle the -c flag themselves.

    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


register_analyze_command(app, ctx_store)
register_resume_command(app, ctx_store)


app.add_typer(config_app, name="config")
app.add_typer(doctor_app, name="doctor")
app.add_typer(plugin_app, name="plugin")
app.add_typer(runs_app, name="runs")
if bool(os.environ.get("LB_ENABLE_TEST_CLI")) or ctx_store.dev_mode:
    app.add_typer(test_app, name="test")
else:
    @app.command("test")
    def _test_disabled() -> None:
        """Hide test helpers when not installed in dev mode."""
        ctx_store.ui.present.error(
            "`lb test` is available only in dev installs. "
            "Run `LB_ENABLE_TEST_CLI=1 lb test ...` or create .lb_dev_cli to override."
        )
        raise typer.Exit(1)


register_run_command(
    app=app,
    ctx=ctx_store,
)






@app.command("plugins", hidden=True)
def list_plugins() -> None:
    """Compatibility alias for plugin list."""
    ctx_store.ui.present.info("Use `lb plugin list`.")


def main() -> None:
    """Console script entrypoint (Typer app)."""
    app()


if __name__ == "__main__":
    main()
