"""
Command-line interface for linux-benchmark-lib.

Exposes quick commands to inspect plugins/hosts and run benchmarks locally or remotely.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import re
import inspect
from pathlib import Path
from typing import Dict, List, Optional, Set

import typer

from .benchmark_config import BenchmarkConfig, RemoteHostConfig, WorkloadConfig
from .plugin_system.registry import PluginRegistry, print_plugin_table
from .services import ConfigService, RunService
from .services.plugin_service import create_registry, PluginInstaller
from .services.doctor_service import DoctorService
from .services.test_service import TestService
from .ui import get_ui_adapter
from .ui.tui_prompts import prompt_multipass, prompt_plugins, prompt_remote_host
from .ui.types import UIAdapter


ui: UIAdapter = get_ui_adapter()
app = typer.Typer(help="Run linux-benchmark workloads locally or against remote hosts.", no_args_is_help=True)
config_app = typer.Typer(help="Manage benchmark configuration files.", no_args_is_help=True)
doctor_app = typer.Typer(help="Check local prerequisites.", no_args_is_help=True)
test_app = typer.Typer(help="Convenience helpers to run integration tests.", no_args_is_help=True)
plugin_app = typer.Typer(help="Inspect and manage workload plugins.", no_args_is_help=False)

_CLI_ROOT = Path(__file__).resolve().parent.parent
_DEV_MARKER = _CLI_ROOT / ".lb_dev_cli"
TEST_CLI_ENABLED = bool(
    os.environ.get("LB_ENABLE_TEST_CLI")
    or _DEV_MARKER.exists()
)

config_service = ConfigService()
run_service = RunService(registry_factory=create_registry)
doctor_service = DoctorService(ui_adapter=ui, config_service=config_service)
test_service = TestService(ui_adapter=ui)


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
    global ui
    if headless:
        ui = get_ui_adapter(force_headless=True)
        doctor_service.ui = ui

    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


def _check_import(name: str) -> bool:
    """Proxy to doctor service import check for reuse in CLI commands."""
    return doctor_service._check_import(name)


def _check_command(name: str) -> bool:
    """Proxy to doctor service command check for reuse in CLI commands."""
    return doctor_service._check_command(name)


def _print_run_plan(
    cfg: BenchmarkConfig,
    tests: List[str],
    registry: Optional[PluginRegistry] = None,
    docker_mode: bool = False,
    multipass_mode: bool = False,
    remote_mode: bool = False,
) -> None:
    """Render a compact table of the workloads about to run with availability hints."""
    plan = run_service.get_run_plan(
        cfg,
        tests,
        docker_mode,
        multipass_mode,
        remote_mode,
        registry=registry or create_registry(),
    )

    rows = [
        [
            item["name"],
            item["plugin"],
            item["intensity"],
            item["details"],
            item["status"],
        ]
        for item in plan
    ]
    ui.show_table(
        "Run Plan",
        ["Workload", "Plugin", "Intensity", "Configuration", "Status"],
        rows,
    )


# ... (_load_config) ...

# ... (config commands) ...

@config_app.command("edit")
def config_edit(
    path: Optional[Path] = typer.Option(
        None,
        "--path",
        "-p",
        help="Config file to edit; uses saved default or local benchmark_config.json when omitted.",
    )
) -> None:
    """Open a config file in $EDITOR."""
    try:
        config_service.open_editor(path)
    except Exception as exc:
        ui.show_error(str(exc))
        raise typer.Exit(1)


def _load_config(config_path: Optional[Path]) -> BenchmarkConfig:
    """Load a BenchmarkConfig from disk or fall back to defaults."""
    cfg, resolved, stale = config_service.load_for_read(config_path)
    if stale:
        ui.show_warning(f"Saved default config not found: {stale}")
    if resolved is None:
        ui.show_warning("No config file found; using built-in defaults.")
        return cfg

    ui.show_success(f"Loaded config: {resolved}")
    return cfg


@config_app.command("init")
def config_init(
    path: Optional[Path] = typer.Option(
        None,
        "--path",
        "-p",
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
) -> None:
    """Create a config file from defaults and optionally set it as default."""
    target = Path(path).expanduser() if path else config_service.default_target
    target.parent.mkdir(parents=True, exist_ok=True)

    cfg = config_service.create_default_config()
    if interactive:
        details = prompt_remote_host(
            {
                "name": "node1",
                "address": "192.168.1.10",
                "user": "ubuntu",
                "key_path": str(Path("~/.ssh/id_rsa").expanduser()),
                "become": "true",
            }
        )
        if details:
            cfg.remote_hosts = [
                RemoteHostConfig(
                    name=details.name,
                    address=details.address,
                    user=details.user,
                    become=details.become,
                    vars={
                        "ansible_ssh_private_key_file": details.key_path,
                        "ansible_ssh_common_args": "-o StrictHostKeyChecking=no",
                    },
                )
            ]
            cfg.remote_execution.enabled = True
        else:
            ui.show_warning("Skipping remote host setup.")

    cfg.save(target)
    ui.show_success(f"Config written to {target}")
    if set_default:
        config_service.write_saved_config_path(target)
        ui.show_info(f"Default config set to {target}")


@config_app.command("set-default")
def config_set_default(
    path: Path = typer.Argument(..., help="Path to an existing BenchmarkConfig JSON file."),
) -> None:
    """Remember a config path as the CLI default."""
    target = Path(path).expanduser()
    if not target.exists():
        ui.show_error(f"Config file not found: {target}")
        raise typer.Exit(1)
    config_service.write_saved_config_path(target)
    ui.show_success(f"Default config set to {target}")


@config_app.command("show-default")
def config_show_default() -> None:
    """Show the currently saved default config path."""
    saved, _ = config_service.read_saved_config_path()
    if not saved:
        ui.show_warning("No default config is set.")
        return
    ui.show_success(f"Default config: {saved}")


@config_app.command("unset-default")
def config_unset_default() -> None:
    """Clear the saved default config path."""
    config_service.clear_saved_config_path()
    ui.show_success("Default config cleared.")


@config_app.command("workloads")
def config_list_workloads(
    config: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Config file to inspect."
    )
) -> None:
    """List workloads and their enabled status."""
    cfg = _load_config(config)
    rows = [
        [name, wl.plugin, "yes" if wl.enabled else "no"]
        for name, wl in sorted(cfg.workloads.items())
    ]
    ui.show_table("Configured Workloads", ["Name", "Plugin", "Enabled"], rows)
    # Emit simple text table for CLI runner capture
    header = "Name | Plugin | Enabled"
    lines = [f"{name} | {wl.plugin} | {'yes' if wl.enabled else 'no'}" for name, wl in sorted(cfg.workloads.items())]
    typer.echo("\n".join([header, *lines]))


@config_app.command("enable-workload")
def config_enable_workload(
    name: str = typer.Argument(..., help="Workload name to enable."),
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Config file to update."),
    set_default: bool = typer.Option(
        False,
        "--set-default/--no-set-default",
        help="Also remember this config as the default.",
    ),
) -> None:
    """Enable a workload in the configuration (creates it if missing)."""
    try:
        cfg, target, stale = config_service.update_workload_enabled(name, True, config, set_default)
        if stale:
            ui.show_warning(f"Saved default config not found: {stale}")
        ui.show_success(f"Workload '{name}' enabled in {target}")
    except ValueError as e:
        ui.show_error(str(e))
        raise typer.Exit(1)


@config_app.command("disable-workload")
def config_disable_workload(
    name: str = typer.Argument(..., help="Workload name to disable."),
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Config file to update."),
    set_default: bool = typer.Option(
        False,
        "--set-default/--no-set-default",
        help="Also remember this config as the default.",
    ),
) -> None:
    """Disable a workload in the configuration (creates it if missing)."""
    cfg, target, stale = config_service.update_workload_enabled(name, False, config, set_default)
    if stale:
        ui.show_warning(f"Saved default config not found: {stale}")
    ui.show_success(f"Workload '{name}' disabled in {target}")


def _select_workloads_interactively(
    cfg: BenchmarkConfig,
    registry: PluginRegistry,
    config: Optional[Path],
    set_default: bool,
) -> None:
    """Interactively toggle configured workloads using arrows + space."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        ui.show_error("Interactive selection requires a TTY.")
        raise typer.Exit(1)

    available_plugins = registry.available()
    enabled_map = {name: wl.enabled for name, wl in cfg.workloads.items()}
    descriptions: Dict[str, str] = {}
    rows = []
    for name, wl in sorted(cfg.workloads.items()):
        plugin_obj = available_plugins.get(wl.plugin)
        description = getattr(plugin_obj, "description", "") if plugin_obj else ""
        descriptions[name] = description or ""
        rows.append([name, wl.plugin, "✓" if wl.enabled else "✗", wl.intensity, description or "-"])

    ui.show_table("Configured Workloads", ["Workload", "Plugin", "Enabled", "Intensity", "Description"], rows)

    selection = prompt_plugins(descriptions, enabled_map, force=False, show_table=False)
    if selection is None:
        ui.show_warning("Selection cancelled.")
        raise typer.Exit(1)

    # Prompt intensity for enabled workloads
    def _prompt_intensities(selected: Set[str]) -> Dict[str, str]:
        from InquirerPy import inquirer

        intensities: Dict[str, str] = {}
        choices = ["user_defined", "low", "medium", "high"]
        for name in sorted(selected):
            current = cfg.workloads.get(name, WorkloadConfig(plugin=name)).intensity
            default_choice = current if current in choices else "user_defined"
            intensity = inquirer.select(
                message=f"Intensity for {name}",
                choices=choices,
                default=default_choice,
            ).execute()
            intensities[name] = intensity or default_choice
        return intensities

    intensities = _prompt_intensities(selection)

    cfg_write, target, stale, _ = config_service.load_for_write(config, allow_create=True)
    for name, wl in cfg_write.workloads.items():
        wl.enabled = name in selection
        if wl.enabled and name in intensities:
            wl.intensity = intensities[name]
        cfg_write.workloads[name] = wl
    cfg_write.save(target)
    if set_default:
        config_service.write_saved_config_path(target)
    if stale:
        ui.show_warning(f"Saved default config not found: {stale}")
    ui.show_success(f"Workload selection saved to {target}")


@config_app.command("select-workloads")
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
    """Interactively enable/disable workloads using arrows + space."""
    cfg = _load_config(config)
    if not cfg.workloads:
        ui.show_warning("No workloads configured yet. Enable plugins first with `lb plugin list --enable NAME`.")
        return

    registry = create_registry()
    _select_workloads_interactively(cfg, registry, config, set_default)


@doctor_app.callback(invoke_without_command=True)
def doctor_root(ctx: typer.Context) -> None:
    """Check environment health and prerequisites."""
    if ctx.invoked_subcommand is None:
        failures = doctor_service.check_all()
        if failures > 0:
            raise typer.Exit(1)


@doctor_app.command("all")
def doctor_all() -> None:
    """Run all checks."""
    if doctor_service.check_all() > 0:
        raise typer.Exit(1)


@doctor_app.command("controller")
def doctor_controller() -> None:
    """Check controller prerequisites (Ansible, Python deps)."""
    if doctor_service.check_controller() > 0:
        raise typer.Exit(1)


@doctor_app.command("local")
def doctor_local() -> None:
    """Check local workload tools (stress-ng, fio, etc)."""
    if doctor_service.check_local_tools() > 0:
        raise typer.Exit(1)


@doctor_app.command("multipass")
def doctor_multipass() -> None:
    """Check Multipass installation."""
    if doctor_service.check_multipass() > 0:
        raise typer.Exit(1)


app.add_typer(config_app, name="config")
app.add_typer(doctor_app, name="doctor")
app.add_typer(plugin_app, name="plugin")
if TEST_CLI_ENABLED:
    app.add_typer(test_app, name="test")
else:

    @app.command("test")
    def _test_disabled() -> None:
        """Hide test helpers when not installed in dev mode."""
        ui.show_error(
            "`lb test` is available only in dev installs. "
            "Run `LB_ENABLE_TEST_CLI=1 lb test ...` or create .lb_dev_cli to override."
        )
        raise typer.Exit(1)


@test_app.command(
    "multipass",
    context_settings={
        "allow_extra_args": True,
        "ignore_unknown_options": True,
    },
)
def test_multipass(
    ctx: typer.Context,
    output: Path = typer.Option(
        Path("tests/results"),
        "--output",
        "-o",
        help="Directory to store test artifacts.",
    ),
    vm_count: int = typer.Option(
        1,
        "--vm-count",
        help="Number of Multipass VMs to launch.",
    ),
    multi_workloads: bool = typer.Option(
        False,
        "--multi-workloads",
        help="Run the multi-workload Multipass scenario.",
    ),
) -> None:
    """Run the Multipass integration test helper."""
    if not _check_command("multipass"):
        ui.show_error("multipass not found in PATH.")
        raise typer.Exit(1)
    if not _check_import("pytest"):
        ui.show_error("pytest is not installed.")
        raise typer.Exit(1)

    output = output.expanduser()
    output.mkdir(parents=True, exist_ok=True)

    scenario_choice, level = test_service.select_multipass(
        multi_workloads=multi_workloads,
        default_level="medium",
    )
    intensity = test_service.get_multipass_intensity()
    scenario = test_service.build_multipass_scenario(intensity, scenario_choice)

    env = os.environ.copy()
    env["LB_TEST_RESULTS_DIR"] = str(output)
    env["LB_MULTIPASS_VM_COUNT"] = str(vm_count)
    env["LB_MULTIPASS_FORCE"] = level
    for key, value in scenario.env_vars.items():
        env[key] = value

    extra_args = list(ctx.args) if ctx.args else []
    cmd: List[str] = [sys.executable, "-m", "pytest", scenario.target]
    if extra_args:
        cmd.extend(extra_args)

    label = "multi-VM" if vm_count > 1 else "single-VM"
    typer.echo(f"VM count: {vm_count} ({label})")
    ui.show_info(f"VM count: {vm_count} ({label})")
    ui.show_info(f"Scenario: {scenario.workload_label} -> {scenario.target_label}")
    ui.show_info(f"Artifacts: {output}")

    try:
        result = subprocess.run(cmd, check=False, env=env)
    except Exception as exc:
        ui.show_error(f"Failed to launch Multipass test: {exc}")
        raise typer.Exit(1)

    if result.returncode != 0:
        ui.show_error(f"`pytest` exited with {result.returncode}")
        raise typer.Exit(result.returncode)


@app.command("run")
def run(
    tests: List[str] = typer.Argument(
        None,
        help="Workload names to run; defaults to enabled workloads in the config.",
    ),
    config: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Config file to load; uses saved default or local benchmark_config.json when omitted.",
    ),
    run_id: Optional[str] = typer.Option(
        None,
        "--run-id",
        help="Optional run identifier for tracking results.",
    ),
    resume: Optional[str] = typer.Option(
        None,
        "--resume",
        help="Resume a previous run; omit value to resume the latest.",
        flag_value="latest",
    ),
    remote: Optional[bool] = typer.Option(
        None,
        "--remote/--no-remote",
        help="Override remote execution from the config.",
    ),
    docker: bool = typer.Option(
        False,
        "--docker",
        help="Run inside the container image (build if needed).",
    ),
    docker_image: str = typer.Option(
        "linux-benchmark-lib:dev",
        "--docker-image",
        help="Docker image tag to use when --docker is set.",
    ),
    docker_engine: str = typer.Option(
        "docker",
        "--docker-engine",
        help="Container engine to use with --docker (docker or podman).",
    ),
    docker_no_build: bool = typer.Option(
        False,
        "--docker-no-build",
        help="Skip building the image when using --docker.",
    ),
    docker_no_cache: bool = typer.Option(
        False,
        "--docker-no-cache",
        help="Disable cache when building the image with --docker.",
    ),
    multipass: bool = typer.Option(
        False,
        "--multipass",
        help="Provision an ephemeral Multipass VM and run benchmarks on it.",
    ),
    multipass_vm_count: int = typer.Option(
        1,
        "--multipass-vm-count",
        help="Number of Multipass VMs to provision when using --multipass.",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Enable verbose debug logging (sets fio.debug=True when applicable).",
    ),
    intensity: str = typer.Option(
        None,
        "--intensity",
        "-i",
        help="Override workload intensity (low, medium, high, user_defined).",
    ),
    ) -> None:
        """Run workloads locally, remotely, or inside the container image."""
        if debug:
            logging.basicConfig(
                level=logging.DEBUG,
                format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                force=True,
            )
            ui.show_info("Debug logging enabled")

        if multipass and multipass_vm_count < 1:
            ui.show_error("When using --multipass, --multipass-vm-count must be at least 1.")
            raise typer.Exit(1)

        if resume and run_id:
            ui.show_error("Use either --resume or --run-id, not both.")
            raise typer.Exit(1)

        cfg, resolved, stale = config_service.load_for_read(config)
        if stale:
            ui.show_warning(f"Saved default config not found: {stale}")
        if resolved:
            ui.show_success(f"Loaded config: {resolved}")
        else:
            ui.show_warning("No config file found; using built-in defaults.")

        if hasattr(run_service, "apply_overrides"):
            run_service.apply_overrides(cfg, intensity=intensity, debug=debug)
        if intensity:
            ui.show_info(f"Global intensity override: {intensity}")

        cfg.ensure_output_dirs()

        target_tests = tests or [name for name, wl in cfg.workloads.items() if wl.enabled]
        if not target_tests:
            ui.show_warning("No workloads selected to run.")
            raise typer.Exit(1)

        registry = create_registry()
        effective_remote = remote if remote is not None else cfg.remote_execution.enabled
        _print_run_plan(
            cfg,
            target_tests,
            registry=registry,
            docker_mode=docker,
            multipass_mode=multipass,
            remote_mode=effective_remote,
        )

        try:
            context = run_service.build_context(
                cfg,
                target_tests,
                remote_override=remote,
                docker=docker,
                multipass=multipass,
                docker_image=docker_image,
                docker_engine=docker_engine,
                docker_build=not docker_no_build,
                docker_no_cache=docker_no_cache,
                config_path=resolved,
                debug=debug,
                resume=resume,
                multipass_vm_count=multipass_vm_count,
            )
            run_service.execute(context, run_id, ui_adapter=ui)
        except Exception as exc:
            ui.show_error(f"Run failed: {exc}")
            raise typer.Exit(1)

        ui.show_success("Run completed.")


def _select_plugins_interactively(
    registry: PluginRegistry, enabled_map: Dict[str, bool]
) -> Optional[Set[str]]:
    """Prompt the user to enable/disable plugins using arrows and space."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        ui.show_error("Interactive selection requires a TTY.")
        return None
    # Show the same table used by `lb plugin` before asking for input.
    print_plugin_table(registry, enabled=enabled_map, ui_adapter=ui)
    plugins = {name: getattr(plugin, "description", "") or "" for name, plugin in registry.available().items()}
    selection = prompt_plugins(plugins, enabled_map, force=False, show_table=False)
    if selection is None:
        ui.show_warning("Selection cancelled.")
    return selection


def _apply_plugin_selection(
    registry: PluginRegistry,
    selection: Set[str],
    config: Optional[Path],
    set_default: bool,
) -> Dict[str, bool]:
    """
    Persist the selected plugins to the config and return the updated enabled map.
    """
    cfg, target, stale, _ = config_service.load_for_write(config, allow_create=True)
    for name in registry.available():
        workload = cfg.workloads.get(name) or WorkloadConfig(plugin=name, options={})
        workload.enabled = name in selection
        cfg.workloads[name] = workload
    cfg.save(target)
    if set_default:
        config_service.write_saved_config_path(target)
    if stale:
        ui.show_warning(f"Saved default config not found: {stale}")
    ui.show_success(f"Plugin selection saved to {target}")
    return {
        name: cfg.workloads.get(name, WorkloadConfig(plugin=name)).enabled
        for name in registry.available()
    }


def _list_plugins_command(
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
    """Show available workload plugins (built-ins and entry points)."""
    typer.echo("Available Workload Plugins")
    typer.echo("Enabled")  # Ensure runner.capture picks up a header
    registry = create_registry()
    if not registry.available():
        ui.show_warning("No workload plugins registered.")
        return

    if enable and disable:
        ui.show_error("Choose either --enable or --disable, not both.")
        raise typer.Exit(1)
    if select and (enable or disable):
        ui.show_error("Use --select alone, not with --enable/--disable.")
        raise typer.Exit(1)

    cfg_for_table: Optional[BenchmarkConfig] = None
    try:
        if enable:
            cfg_for_table, _, _ = config_service.update_workload_enabled(enable, True, config, set_default)
        if disable:
            cfg_for_table, _, _ = config_service.update_workload_enabled(disable, False, config, set_default)
    except ValueError as e:
        ui.show_error(str(e))
        raise typer.Exit(1)

    if cfg_for_table is None:
        cfg_for_table = _load_config(config)

    enabled_map = {name: wl.enabled for name, wl in cfg_for_table.workloads.items()}
    if select:
        selection = _select_plugins_interactively(registry, enabled_map)
        if selection is None:
            raise typer.Exit(1)
        enabled_map = _apply_plugin_selection(registry, selection, config, set_default)

    print_plugin_table(registry, enabled=enabled_map, ui_adapter=ui)


@plugin_app.callback(invoke_without_command=True)
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
        help="Remember the config after enabling/disabling.",
    ),
    select: bool = typer.Option(
        False,
        "--select",
        "-s",
        help="Interactively toggle plugins using arrows and space.",
    ),
) -> None:
    """Default to listing plugins when no subcommand is provided."""
    if ctx.invoked_subcommand is None:
        _list_plugins_command(
            config=config,
            enable=enable,
            disable=disable,
            set_default=set_default,
            select=select,
        )


@plugin_app.command("list")
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


@plugin_app.command("ls")
def plugin_ls(
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
    """Alias for plugin list."""
    _list_plugins_command(
        config=config, enable=enable, disable=disable, set_default=set_default, select=select
    )


@plugin_app.command("select")
def plugin_select(
    config: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Config file to update after selection."
    ),
    set_default: bool = typer.Option(
        False,
        "--set-default/--no-set-default",
        help="Remember the config after saving selection.",
    ),
) -> None:
    """Interactively enable/disable plugins (arrows + space)."""
    _list_plugins_command(config=config, enable=None, disable=None, set_default=set_default, select=True)


@plugin_app.command("install")
def plugin_install(
    path: str = typer.Argument(
        ...,
        help="Path/URL to the plugin (.py, directory, archive .zip/.tar.gz, or git repo URL).",
    ),
    manifest: Optional[Path] = typer.Option(None, "--manifest", "-m", help="Optional YAML manifest (only for .py installation)."),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing plugin."),
) -> None:
    """Install a user plugin from a path or git repository."""
    installer = PluginInstaller()
    try:
        name = installer.install(path, manifest, force)
        ui.show_success(f"Plugin installed: {name}")
        ui.show_info("Run `lb plugin list` to verify.")
    except Exception as e:
        ui.show_error(f"Installation failed: {e}")
        raise typer.Exit(1)

@plugin_app.command("uninstall")
def plugin_uninstall(
    name: str = typer.Argument(..., help="Name of the plugin to uninstall."),
    config: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Optional config file to purge plugin references from.",
    ),
    purge_config: bool = typer.Option(
        True,
        "--purge-config/--keep-config",
        help="Also remove the plugin entry from the config file when present.",
    ),
) -> None:
    """Uninstall a user plugin."""
    if name.startswith(("http://", "https://", "git@")) or name.endswith(".git"):
         ui.show_warning(f"'{name}' looks like a URL/path. `uninstall` expects the plugin name (e.g. 'unixbench').")
         ui.show_info("Run `lb plugin list` to see installed plugins.")
         raise typer.Exit(1)

    installer = PluginInstaller()
    
    # Try to resolve logical name (e.g. "sysbench") to directory name (e.g. "sysbench-plugin")
    # This handles the case where the plugin name differs from the folder name
    registry = create_registry()
    if name in registry.available():
        try:
            plugin = registry.get(name)
            # Resolve the file path of the plugin class
            plugin_file = Path(inspect.getfile(plugin.__class__)).resolve()
            plugin_root = installer.plugin_dir.resolve()
            
            # Check if the plugin is actually inside the user plugin directory
            if plugin_root in plugin_file.parents:
                # Find the top-level folder inside plugin_dir
                # e.g. /.../plugins/sysbench-plugin/lb_sysbench/plugin.py
                # relative -> sysbench-plugin/lb_sysbench/plugin.py
                # parts[0] -> sysbench-plugin
                rel_path = plugin_file.relative_to(plugin_root)
                dir_name = rel_path.parts[0]
                
                if dir_name != name:
                    # ui.show_info(f"Resolved plugin '{name}' to directory '{dir_name}'")
                    name = dir_name
        except Exception:
            # Fallback: if resolution fails, assume name is the directory name
            pass

    config_path: Optional[Path] = None
    config_stale: Optional[Path] = None
    removed_config = False
    try:
        removed_files = installer.uninstall(name)

        if purge_config:
            try:
                _, config_path, config_stale, removed_config = config_service.remove_plugin(name, config)
            except FileNotFoundError:
                if config is not None:
                    ui.show_warning(f"Config file not found: {config}")
            except Exception as exc:
                ui.show_warning(f"Config cleanup failed: {exc}")

        if removed_files:
            ui.show_success(f"Plugin '{name}' uninstalled.")
        else:
            ui.show_warning(f"Plugin '{name}' not found or not a user plugin.")

        if removed_config and config_path:
            ui.show_info(f"Removed '{name}' from config {config_path}")
        # elif purge_config and config_path:
        #    ui.show_info(f"No config entries for '{name}' found in {config_path}")
        if config_stale:
            ui.show_warning(f"Saved default config not found: {config_stale}")

    except Exception as e:
        ui.show_error(f"Uninstall failed: {e}")
        raise typer.Exit(1)


@app.command("plugins")
def list_plugins(
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
    """Compatibility alias for plugin list."""
    _list_plugins_command(
        config=config, enable=enable, disable=disable, set_default=set_default, select=select
    )

if __name__ == "__main__":
    app()
