from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from lb_app.api import (
    BenchmarkConfig,
    PluginRegistry,
    RemoteHostConfig,
    create_registry,
)
from lb_ui.wiring.dependencies import UIContext
from lb_ui.tui.system.models import TableModel
from lb_ui.flows.config_wizard import run_config_wizard
from lb_ui.flows.errors import UIFlowError
from lb_ui.flows.selection import select_workloads_interactively


def create_config_app(ctx: UIContext) -> typer.Typer:
    """Build the config Typer app, wired to the given context."""
    app = typer.Typer(
        help="Manage benchmark configuration files.", no_args_is_help=True
    )

    def _load_config(config_path: Optional[Path]) -> BenchmarkConfig:
        """Load a BenchmarkConfig from disk or fall back to defaults."""
        cfg, resolved, stale = ctx.config_service.load_for_read(config_path)
        if stale:
            ctx.ui.present.warning(f"Saved default config not found: {stale}")
        if resolved is None:
            ctx.ui.present.warning("No config file found; using built-in defaults.")
            return cfg

        ctx.ui.present.success(f"Loaded config: {resolved}")
        return cfg

    @app.command("edit")
    def config_edit(
        config_path: Optional[Path] = typer.Option(
            None,
            "--config",
            "-c",
            help=(
                "Config file to edit; uses saved default or local "
                "benchmark_config.json when omitted."
            ),
        )
    ) -> None:
        """Open a config file in $EDITOR."""
        try:
            ctx.config_service.open_editor(config_path)
        except Exception as exc:
            ctx.ui.present.error(str(exc))
            raise typer.Exit(1)

    @app.command("init")
    def config_init(
        config_path: Optional[Path] = typer.Option(
            None,
            "--config",
            "-c",
            help="Where to write the config; defaults to ~/.config/lb/config.json",
        ),
        set_default: bool = typer.Option(
            True,
            "--set-default/--no-set-default",
            help="Save this config as the default for future commands.",
        ),
        interactive: bool = typer.Option(
            False,
            "--interactive",
            "-i",
            help="Prompt for a remote host while creating the config.",
        ),
        repetitions: int = typer.Option(
            3,
            "--repetitions",
            "-r",
            help="Number of repetitions to run for each workload (must be >= 1).",
        ),
    ) -> None:
        """Create a config file from defaults and optionally set it as default."""
        target = (
            Path(config_path).expanduser()
            if config_path
            else ctx.config_service.default_target
        )
        target.parent.mkdir(parents=True, exist_ok=True)

        if repetitions < 1:
            ctx.ui.present.error("Repetitions must be at least 1.")
            raise typer.Exit(1)

        cfg = ctx.config_service.create_default_config()
        cfg.repetitions = repetitions
        if interactive:
            run_config_wizard(ctx.ui, cfg)

        cfg.save(target)
        ctx.ui.present.success(f"Config written to {target}")
        if set_default:
            ctx.config_service.write_saved_config_path(target)
            ctx.ui.present.info(f"Default config set to {target}")

    @app.command("set-repetitions")
    def config_set_repetitions(
        repetitions: int = typer.Argument(
            ..., help="Number of repetitions to store in the config."
        ),
        config: Optional[Path] = typer.Option(
            None, "--config", "-c", help="Config file to update."
        ),
        set_default: bool = typer.Option(
            False,
            "--set-default/--no-set-default",
            help="Remember this config as the default.",
        ),
    ) -> None:
        """Persist the desired repetitions count to the configuration file."""

        if repetitions < 1:
            ctx.ui.present.error("Repetitions must be at least 1.")
            raise typer.Exit(1)

        cfg, target, stale, _ = ctx.config_service.load_for_write(
            config, allow_create=True
        )
        cfg.repetitions = repetitions
        cfg.save(target)

        if set_default:
            ctx.config_service.write_saved_config_path(target)

        if stale:
            ctx.ui.present.warning(f"Saved default config not found: {stale}")
        ctx.ui.present.success(f"Repetitions set to {repetitions} in {target}")

    @app.command("set-default")
    def config_set_default(
        path: Path = typer.Argument(
            ..., help="Path to an existing BenchmarkConfig JSON file."
        ),
    ) -> None:
        """Remember a config path as the CLI default."""
        target = Path(path).expanduser()
        if not target.exists():
            ctx.ui.present.error(f"Config file not found: {target}")
            raise typer.Exit(1)
        ctx.config_service.write_saved_config_path(target)
        ctx.ui.present.success(f"Default config set to {target}")

    @app.command("show-default")
    def config_show_default() -> None:
        """Show the currently saved default config path."""
        saved, _ = ctx.config_service.read_saved_config_path()
        if not saved:
            ctx.ui.present.warning("No default config is set.")
            return
        ctx.ui.present.success(f"Default config: {saved}")

    @app.command("unset-default")
    def config_unset_default() -> None:
        """Clear the saved default config path."""
        ctx.config_service.clear_saved_config_path()
        ctx.ui.present.success("Default config cleared.")

    @app.command("workloads")
    def config_list_workloads(
        config: Optional[Path] = typer.Option(
            None, "--config", "-c", help="Config file to inspect."
        )
    ) -> None:
        """List configured workloads."""
        cfg = _load_config(config)
        rows = [[name, wl.plugin] for name, wl in sorted(cfg.workloads.items())]
        ctx.ui.tables.show(
            TableModel(
                title="Configured Workloads", columns=["Name", "Plugin"], rows=rows
            )
        )

    @app.command("enable-workload")
    def config_enable_workload(
        name: str = typer.Argument(..., help="Workload name to enable."),
        config: Optional[Path] = typer.Option(
            None, "--config", "-c", help="Config file to update."
        ),
        set_default: bool = typer.Option(
            False,
            "--set-default/--no-set-default",
            help="Also remember this config as the default.",
        ),
    ) -> None:
        """Add a workload to the configuration (creates it if missing)."""
        try:
            cfg, target, stale = ctx.config_service.add_workload(
                name, config, set_default
            )
            if stale:
                ctx.ui.present.warning(f"Saved default config not found: {stale}")
            ctx.ui.present.success(f"Workload '{name}' added in {target}")
        except ValueError as e:
            ctx.ui.present.error(str(e))
            raise typer.Exit(1)

    @app.command("disable-workload")
    def config_disable_workload(
        name: str = typer.Argument(..., help="Workload name to disable."),
        config: Optional[Path] = typer.Option(
            None, "--config", "-c", help="Config file to update."
        ),
        set_default: bool = typer.Option(
            False,
            "--set-default/--no-set-default",
            help="Also remember this config as the default.",
        ),
    ) -> None:
        """Remove a workload from the configuration (and its plugin settings)."""
        cfg, target, stale, removed = ctx.config_service.remove_plugin(name, config)
        if stale:
            ctx.ui.present.warning(f"Saved default config not found: {stale}")
        if not removed:
            ctx.ui.present.warning(f"No workload named '{name}' found in the config.")
        if set_default:
            ctx.config_service.write_saved_config_path(target)
        ctx.ui.present.success(f"Workload '{name}' removed from {target}")

    def _select_workloads_interactively(
        cfg: BenchmarkConfig,
        registry: PluginRegistry,
        config: Optional[Path],
        set_default: bool,
    ) -> None:
        """Interactively toggle configured workloads using arrows + space."""
        try:
            select_workloads_interactively(
                ctx.ui, ctx.config_service, cfg, registry, config, set_default
            )
        except UIFlowError as exc:
            ctx.ui.present.error(str(exc))
            raise typer.Exit(exc.exit_code)

    @app.command("select-workloads")
    def config_select_workloads(
        config: Optional[Path] = typer.Option(
            None, "--config", "-c", help="Config file to update after selection."
        ),
        set_default: bool = typer.Option(
            False,
            "--set-default/--no-set-default",
            help="Remember the config after saving selection.",
        ),
    ) -> None:
        """Interactively toggle workloads using arrows + space."""
        cfg = _load_config(config)
        if not cfg.workloads:
            ctx.ui.present.warning(
                "No workloads configured yet. Add workloads with "
                "`lb config enable-workload NAME`."
            )
            return

        registry = create_registry()
        _select_workloads_interactively(cfg, registry, config, set_default)

    @app.command("hosts")
    def config_list_hosts(
        config: Optional[Path] = typer.Option(
            None, "--config", "-c", help="Config file to inspect."
        )
    ) -> None:
        """List configured remote hosts."""
        cfg = _load_config(config)
        if not cfg.remote_hosts:
            ctx.ui.present.warning("No remote hosts configured.")
            ctx.ui.present.info("Add hosts with `lb config add-host NAME --address IP`")
            return

        rows = [
            [h.name, h.address, str(h.port), h.user, "Yes" if h.become else "No"]
            for h in cfg.remote_hosts
        ]
        ctx.ui.tables.show(
            TableModel(
                title="Remote Hosts",
                columns=["Name", "Address", "Port", "User", "Become"],
                rows=rows,
            )
        )

    @app.command("add-host")
    def config_add_host(
        name: str = typer.Argument(..., help="Unique name for the host."),
        address: str = typer.Option(
            ..., "--address", "-a", help="IP address or hostname."
        ),
        port: int = typer.Option(22, "--port", "-p", help="SSH port."),
        user: str = typer.Option("root", "--user", "-u", help="SSH user."),
        key: Optional[str] = typer.Option(
            None, "--key", "-k", help="Path to SSH private key."
        ),
        become: bool = typer.Option(
            True, "--become/--no-become", help="Use sudo (Ansible become)."
        ),
        config: Optional[Path] = typer.Option(
            None, "--config", "-c", help="Config file to update."
        ),
        set_default: bool = typer.Option(
            False,
            "--set-default/--no-set-default",
            help="Also remember this config as the default.",
        ),
    ) -> None:
        """Add or update a remote host in the configuration."""
        # Build vars dict with SSH key if provided
        host_vars: dict = {
            "ansible_ssh_common_args": "-o StrictHostKeyChecking=no",
        }
        if key:
            key_path = Path(key).expanduser()
            if not key_path.exists():
                ctx.ui.present.warning(f"SSH key not found: {key_path}")
            host_vars["ansible_ssh_private_key_file"] = str(key_path)

        host = RemoteHostConfig(
            name=name,
            address=address,
            port=port,
            user=user,
            become=become,
            vars=host_vars,
        )

        try:
            cfg, target, stale = ctx.config_service.add_remote_host(
                host, config, enable_remote=True, set_default=set_default
            )
            if stale:
                ctx.ui.present.warning(f"Saved default config not found: {stale}")
            ctx.ui.present.success(
                f"Host '{name}' ({address}:{port}) added to {target}"
            )
        except ValueError as e:
            ctx.ui.present.error(str(e))
            raise typer.Exit(1)

    @app.command("remove-host")
    def config_remove_host(
        name: str = typer.Argument(..., help="Name of the host to remove."),
        config: Optional[Path] = typer.Option(
            None, "--config", "-c", help="Config file to update."
        ),
    ) -> None:
        """Remove a remote host from the configuration."""
        try:
            cfg, target, stale, removed = ctx.config_service.remove_remote_host(
                name, config
            )
            if stale:
                ctx.ui.present.warning(f"Saved default config not found: {stale}")
            if not removed:
                ctx.ui.present.warning(f"No host named '{name}' found in the config.")
                raise typer.Exit(1)
            ctx.ui.present.success(f"Host '{name}' removed from {target}")
            if not cfg.remote_hosts:
                ctx.ui.present.info("No hosts remaining. Remote execution disabled.")
        except FileNotFoundError as e:
            ctx.ui.present.error(str(e))
            raise typer.Exit(1)

    return app
