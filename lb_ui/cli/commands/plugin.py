from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from lb_controller.api import ConfigService, create_registry, build_plugin_table
from lb_ui.tui.system.models import TableModel
from lb_ui.flows.selection import select_plugins_interactively, apply_plugin_selection


def create_plugin_app(config_service: ConfigService, ui) -> typer.Typer:
    """Build the plugin Typer app (list/manage workload plugins)."""
    app = typer.Typer(help="Inspect and manage workload plugins.", no_args_is_help=False)

    def _load_config(config_path: Optional[Path]):
        cfg, resolved, stale = config_service.load_for_read(config_path)
        if stale:
            ui.present.warning(f"Saved default config not found: {stale}")
        if resolved is None:
            ui.present.warning("No config file found; using built-in defaults.")
            return cfg
        ui.present.success(f"Loaded config: {resolved}")
        return cfg

    def _list_plugins_command(
        config: Optional[Path],
        enable: Optional[str],
        disable: Optional[str],
        set_default: bool,
        select: bool,
    ) -> None:
        registry = create_registry()
        if not registry.available():
            ui.present.warning("No workload plugins registered.")
            return

        if enable and disable:
            ui.present.error("Choose either --enable or --disable, not both.")
            raise typer.Exit(1)
        if select and (enable or disable):
            ui.present.error("Use --select alone, not with --enable/--disable.")
            raise typer.Exit(1)

        cfg_for_table = None
        try:
            if enable:
                cfg_for_table, _, _ = config_service.update_workload_enabled(enable, True, config, set_default)
            if disable:
                cfg_for_table, _, _ = config_service.update_workload_enabled(disable, False, config, set_default)
        except ValueError as e:
            ui.present.error(str(e))
            raise typer.Exit(1)

        if cfg_for_table is None:
            cfg_for_table = _load_config(config)

        enabled_map = {name: wl.enabled for name, wl in cfg_for_table.workloads.items()}
        if select:
            selection = select_plugins_interactively(ui, registry, enabled_map)
            if selection is None:
                raise typer.Exit(1)
            enabled_map = apply_plugin_selection(ui, config_service, registry, selection, config, set_default)

        headers, rows = build_plugin_table(registry, enabled=enabled_map)
        ui.tables.show(TableModel(title="Available Workload Plugins", columns=headers, rows=rows))

    @app.callback(invoke_without_command=True)
    def plugin_root(
        ctx: typer.Context,
        config: Optional[Path] = typer.Option(
            None, "--config", "-c", help="Config file to update when enabling/disabling."
        ),
        enable: Optional[str] = typer.Option(
            None, "--enable", help="Enable a workload using the given plugin name."
        ),
        disable: Optional[str] = typer.Option(
            None, "--disable", help="Disable a workload using the given plugin name."
        ),
        set_default: bool = typer.Option(
            False,
            "--set-default/--no-set-default",
            help="Remember the config after enabling/disabling."
        ),
        select: bool = typer.Option(
            False,
            "--select",
            "-s",
            help="Interactively toggle plugins using arrows and space.",
        ),
    ) -> None:
        if ctx.invoked_subcommand is None:
            _list_plugins_command(
                config=config,
                enable=enable,
                disable=disable,
                set_default=set_default,
                select=select,
            )

    @app.command("list")
    def plugin_list(
        config: Optional[Path] = typer.Option(
            None, "--config", "-c", help="Config file to update when enabling/disabling."
        ),
        enable: Optional[str] = typer.Option(
            None, "--enable", help="Enable a workload using the given plugin name."
        ),
        disable: Optional[str] = typer.Option(
            None, "--disable", help="Disable a workload using the given plugin name."
        ),
        set_default: bool = typer.Option(
            False,
            "--set-default/--no-set-default",
            help="Remember the config after enabling/disabling.",
        ),
        select: bool = typer.Option(
            False,
            "--select",
            "-s",
            help="Interactively toggle plugins using arrows and space.",
        ),
    ) -> None:
        """List workload plugins with enabled status."""
        _list_plugins_command(
            config=config, enable=enable, disable=disable, set_default=set_default, select=select
        )

    @app.command("select")
    def plugin_select(
        config: Optional[Path] = typer.Option(
            None, "--config", "-c", help="Config file to update when enabling/disabling."
        ),
        set_default: bool = typer.Option(
            False,
            "--set-default/--no-set-default",
            help="Remember the config after enabling/disabling.",
        ),
    ) -> None:
        """Interactive plugin selection (compatibility command)."""
        _list_plugins_command(
            config=config,
            enable=None,
            disable=None,
            set_default=set_default,
            select=True,
        )

    return app
