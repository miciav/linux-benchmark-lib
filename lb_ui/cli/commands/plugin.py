from __future__ import annotations

from typing import Optional

import typer

from lb_app.api import build_plugin_table, create_registry
from lb_ui.wiring.dependencies import UIContext
from lb_ui.tui.system.models import TableModel
from lb_ui.flows.selection import select_plugins_interactively, apply_plugin_selection


def create_plugin_app(ctx: UIContext) -> typer.Typer:
    """Build the plugin Typer app (list/manage workload plugins)."""
    app = typer.Typer(help="Inspect and manage workload plugins.", no_args_is_help=False)

    def _load_platform():
        cfg, resolved, exists = ctx.config_service.load_platform_config()
        if not exists:
            ctx.ui.present.warning("No platform config found; using defaults.")
            return cfg
        ctx.ui.present.success(f"Loaded platform config: {resolved}")
        return cfg

    def _list_plugins_command(
        enable: Optional[str],
        disable: Optional[str],
        select: bool,
    ) -> None:
        registry = create_registry()
        if not registry.available():
            ctx.ui.present.warning("No workload plugins registered.")
            return

        if enable and disable:
            ctx.ui.present.error("Choose either --enable or --disable, not both.")
            raise typer.Exit(1)
        if select and (enable or disable):
            ctx.ui.present.error("Use --select alone, not with --enable/--disable.")
            raise typer.Exit(1)

        cfg_for_table = None
        try:
            if enable:
                if enable not in registry.available():
                    raise ValueError(
                        f"Plugin '{enable}' is not installed. Use `lb plugin list` to see available plugins."
                    )
                cfg_for_table, _ = ctx.config_service.set_plugin_enabled(enable, True)
            if disable:
                if disable not in registry.available():
                    raise ValueError(
                        f"Plugin '{disable}' is not installed. Use `lb plugin list` to see available plugins."
                    )
                cfg_for_table, _ = ctx.config_service.set_plugin_enabled(disable, False)
        except ValueError as e:
            ctx.ui.present.error(str(e))
            raise typer.Exit(1)

        if cfg_for_table is None:
            cfg_for_table = _load_platform()

        enabled_map = {
            name: cfg_for_table.is_plugin_enabled(name)
            for name in registry.available()
        }
        if select:
            selection = select_plugins_interactively(ctx.ui, registry, enabled_map)
            if selection is None:
                raise typer.Exit(1)
            enabled_map = apply_plugin_selection(ctx.ui, ctx.config_service, registry, selection)

        headers, rows = build_plugin_table(registry, enabled=enabled_map)
        ctx.ui.tables.show(TableModel(title="Available Workload Plugins", columns=headers, rows=rows))

    @app.callback(invoke_without_command=True)
    def plugin_root(
        typer_ctx: typer.Context,
        enable: Optional[str] = typer.Option(
            None, "--enable", help="Enable a plugin in the platform config."
        ),
        disable: Optional[str] = typer.Option(
            None, "--disable", help="Disable a plugin in the platform config."
        ),
        select: bool = typer.Option(
            False,
            "--select",
            "-s",
            help="Interactively toggle plugins using arrows and space.",
        ),
    ) -> None:
        if typer_ctx.invoked_subcommand is None:
            _list_plugins_command(
                enable=enable,
                disable=disable,
                select=select,
            )

    @app.command("list")
    def plugin_list(
        enable: Optional[str] = typer.Option(
            None, "--enable", help="Enable a plugin in the platform config."
        ),
        disable: Optional[str] = typer.Option(
            None, "--disable", help="Disable a plugin in the platform config."
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
            enable=enable, disable=disable, select=select
        )

    @app.command("select")
    def plugin_select(
    ) -> None:
        """Interactive plugin selection (compatibility command)."""
        _list_plugins_command(
            enable=None,
            disable=None,
            select=True,
        )

    return app
