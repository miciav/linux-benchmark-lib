from __future__ import annotations

import typer

from lb_app.api import build_plugin_table, create_registry
from lb_ui.wiring.dependencies import UIContext
from lb_ui.tui.system.models import TableModel
from lb_ui.flows.errors import UIFlowError
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

    def _ensure_registry():
        registry = create_registry()
        if not registry.available():
            ctx.ui.present.warning("No workload plugins registered.")
            return None
        return registry

    @app.callback(invoke_without_command=True)
    def plugin_root(typer_ctx: typer.Context) -> None:
        if typer_ctx.invoked_subcommand is None:
            typer.echo(typer_ctx.get_help())
            raise typer.Exit()

    @app.command("list")
    def plugin_list() -> None:
        """List workload plugins with enabled status."""
        registry = _ensure_registry()
        if registry is None:
            return

        cfg_for_table = _load_platform()
        enabled_map = {
            name: cfg_for_table.is_plugin_enabled(name)
            for name in registry.available()
        }
        headers, rows = build_plugin_table(registry, enabled=enabled_map)
        ctx.ui.tables.show(
            TableModel(title="Available Workload Plugins", columns=headers, rows=rows)
        )

    @app.command("enable")
    def plugin_enable(
        name: str = typer.Argument(..., help="Plugin name to enable."),
    ) -> None:
        """Enable a plugin in the platform config."""
        registry = _ensure_registry()
        if registry is None:
            raise typer.Exit(1)
        if name not in registry.available():
            ctx.ui.present.error(
                f"Plugin '{name}' is not installed. "
                "Use `lb plugin list` to see available plugins."
            )
            raise typer.Exit(1)
        ctx.config_service.set_plugin_enabled(name, True)
        ctx.ui.present.success(f"Plugin '{name}' enabled.")

    @app.command("disable")
    def plugin_disable(
        name: str = typer.Argument(..., help="Plugin name to disable."),
    ) -> None:
        """Disable a plugin in the platform config."""
        registry = _ensure_registry()
        if registry is None:
            raise typer.Exit(1)
        if name not in registry.available():
            ctx.ui.present.error(
                f"Plugin '{name}' is not installed. "
                "Use `lb plugin list` to see available plugins."
            )
            raise typer.Exit(1)
        ctx.config_service.set_plugin_enabled(name, False)
        ctx.ui.present.success(f"Plugin '{name}' disabled.")

    @app.command("select")
    def plugin_select() -> None:
        """Interactively toggle workload plugins."""
        registry = _ensure_registry()
        if registry is None:
            return

        cfg_for_table = _load_platform()
        enabled_map = {
            name: cfg_for_table.is_plugin_enabled(name)
            for name in registry.available()
        }
        try:
            selection = select_plugins_interactively(ctx.ui, registry, enabled_map)
        except UIFlowError as exc:
            ctx.ui.present.error(str(exc))
            raise typer.Exit(exc.exit_code)
        if selection is None:
            raise typer.Exit(1)

        enabled_map = apply_plugin_selection(
            ctx.ui,
            ctx.config_service,
            registry,
            selection,
        )
        headers, rows = build_plugin_table(registry, enabled=enabled_map)
        ctx.ui.tables.show(
            TableModel(title="Available Workload Plugins", columns=headers, rows=rows)
        )

    return app
