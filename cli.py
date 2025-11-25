"""
Command-line interface for linux-benchmark-lib.

Exposes quick commands to inspect plugins/hosts and run benchmarks locally or remotely.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set

import typer

from benchmark_config import BenchmarkConfig, RemoteHostConfig, WorkloadConfig
from plugins.registry import PluginRegistry, print_plugin_table
from services import ConfigService, RunService, create_registry
from services.doctor_service import DoctorService
from services.test_service import TestService
from ui import get_ui_adapter
from ui.tui_prompts import prompt_multipass, prompt_plugins, prompt_remote_host
from ui.types import UIAdapter


ui: UIAdapter = get_ui_adapter()
app = typer.Typer(help="Run linux-benchmark workloads locally or against remote hosts.")
config_app = typer.Typer(help="Manage benchmark configuration files.")
doctor_app = typer.Typer(help="Check local prerequisites.")
test_app = typer.Typer(help="Convenience helpers to run integration tests.")
plugin_app = typer.Typer(help="Inspect and manage workload plugins.")

_CLI_ROOT = Path(__file__).resolve().parent
_DEV_MARKER = _CLI_ROOT / ".lb_dev_cli"
TEST_CLI_ENABLED = bool(
    os.environ.get("LB_ENABLE_TEST_CLI")
    or _DEV_MARKER.exists()
)

config_service = ConfigService()
run_service = RunService(registry_factory=create_registry)
doctor_service = DoctorService(ui_adapter=ui, config_service=config_service)


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
) -> None:
    """Render a compact table of the workloads about to run with availability hints."""
    plan = run_service.get_run_plan(
        cfg,
        tests,
        docker_mode,
        registry=registry or create_registry(),
    )

    rows = [
        [
            item["name"],
            item["plugin"],
            item["status"],
            item["duration"],
            item["warmup_cooldown"],
            item["repetitions"],
        ]
        for item in plan
    ]
    ui.show_table(
        "Run Plan",
        ["Workload", "Plugin", "Status", "Duration", "Warmup/Cooldown", "Repetitions"],
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

    cfg = BenchmarkConfig()
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
    cfg, target, stale = config_service.update_workload_enabled(name, True, config, set_default)
    if stale:
        ui.show_warning(f"Saved default config not found: {stale}")
    ui.show_success(f"Workload '{name}' enabled in {target}")


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


def _select_plugins_interactively(
    registry: PluginRegistry, enabled_map: Dict[str, bool]
) -> Optional[Set[str]]:
    """Prompt the user to enable/disable plugins using arrows and space."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        ui.show_error("Interactive selection requires a TTY.")
        return None
    plugins = {name: getattr(plugin, "description", "") or "" for name, plugin in registry.available().items()}
    selection = prompt_plugins(plugins, enabled_map, force=False)
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
    if enable:
        cfg_for_table, _, _ = config_service.update_workload_enabled(enable, True, config, set_default)
    if disable:
        cfg_for_table, _, _ = config_service.update_workload_enabled(disable, False, config, set_default)
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


@test_app.command(
    "multipass",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def test_multipass(
    ctx: typer.Context,
    artifacts_dir: Path = typer.Option(
        Path("tests/results"),
        "--artifacts-dir",
        "-o",
        help="Where to store collected artifacts (used via LB_TEST_RESULTS_DIR).",
    ),
    vm_count: int = typer.Option(
        1,
        "--vm-count",
        "-n",
        min=1,
        max=2,
        help="Number of Multipass VMs to launch (default 1, max 2).",
    ),
    multi_workloads: bool = typer.Option(
        False,
        "--multi-workloads",
        help="Run the multi-workload Multipass integration (stress_ng + dd + fio).",
    ),
    top500: bool = typer.Option(
        False,
        "--top500",
        help="Run the Top500 Multipass integration (setup tag only, no HPL run).",
    ),
) -> None:
    """
    Run the Multipass integration test via pytest (launch 1–2 VMs).

    Requires multipass + ansible/ansible-runner installed locally.
    """
    if not _check_command("multipass"):
        ui.show_error("multipass not found in PATH; install it to run this test.")
        raise typer.Exit(1)
    if not _check_import("ansible_runner"):
        ui.show_error("ansible-runner python package not available.")
        raise typer.Exit(1)
    if not _check_command("ansible-playbook"):
        ui.show_error("ansible-playbook not available in PATH.")
        raise typer.Exit(1)
    if multi_workloads and top500:
        ui.show_error("--multi-workloads and --top500 are mutually exclusive.")
        raise typer.Exit(1)

    test_service = TestService(ui)

    # Interactive selection when no mode flags and TTY available
    env_force = os.environ.get("LB_MULTIPASS_FORCE", "medium").strip().lower()

    selection, env_force = test_service.select_multipass(
        multi_workloads, top500, default_level=env_force or "medium"
    )

    intensity = test_service.get_multipass_intensity(env_force)
    scenario = test_service.build_multipass_scenario(intensity, selection)

    artifacts_dir = artifacts_dir.expanduser().resolve()
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["LB_TEST_RESULTS_DIR"] = str(artifacts_dir)
    env["LB_MULTIPASS_VM_COUNT"] = str(vm_count)
    env["LB_MULTIPASS_FORCE"] = env_force
    
    # Apply scenario-specific env vars (e.g. workload selection)
    env.update(scenario.env_vars)
    
    vm_count_label = f"{vm_count} (multi-VM)" if vm_count > 1 else "1"
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        scenario.target,
    ]
    extra_args = list(ctx.args)
    if extra_args:
        cmd.extend(extra_args)

    ui.show_table(
        "Multipass Integration Plan",
        ["Field", "Value"],
        [
            ["Pytest target", scenario.target],
            ["Iterations", "1 (pytest invocation)"],
            ["Workload(s)", scenario.workload_label],
            ["Duration", scenario.duration_label],
            ["Intensity", intensity["level"]],
            ["VM count", vm_count_label],
            ["Artifacts dir", str(artifacts_dir)],
            ["Extra args", " ".join(extra_args) if extra_args else "None"],
            ["Config source", "Embedded in test (not user config)"],
        ],
    )

    ui.show_table(
        "Workload Parameters",
        ["Workload", "Duration", "Repetitions", "Warmup/Cooldown", "Notes"],
        [list(row) for row in scenario.workload_rows],
    )

    try:
        with ui.status(
            f"Running Multipass {scenario.target_label} test on {vm_count_label} VM(s) "
            "(this can take a few minutes)..."
        ):
            subprocess.run(cmd, check=True, env=env)
    except subprocess.CalledProcessError as exc:
        ui.show_error(f"Integration test failed with exit code {exc.returncode}")
        raise typer.Exit(exc.returncode)

    ui.show_panel(
        f"Artifacts saved to: {artifacts_dir}\nCommand: {' '.join(cmd)}",
        title="Integration test completed",
        border_style="green",
    )


def _run_pytest_targets(
    targets: List[str],
    title: str,
    extra_args: Optional[List[str]] = None,
    env: Optional[dict] = None,
) -> None:
    """Execute pytest against the given targets with friendly console output."""
    cmd = [sys.executable, "-m", "pytest"]
    
    # Add default flags for cleaner output
    # -v: verbose (shows test names)
    # --tb=short: shorter tracebacks on failure
    cmd.extend(["-v", "--tb=short"])
    
    cmd.extend(targets)
    if extra_args:
        cmd.extend(extra_args)

    ui.show_rule(title)
    ui.show_info(f"Running: {' '.join(cmd)}")

    try:
        # Run directly to stdout/stderr to avoid buffering issues and allow
        # real-time feedback. We removed the spinner because it conflicts
        # with pytest's live output.
        subprocess.run(cmd, check=True, env=env)

        ui.show_success(f"✔ {title} Passed")
    except subprocess.CalledProcessError as exc:
        ui.show_error(f"✘ {title} Failed (Exit Code: {exc.returncode})")
        raise typer.Exit(exc.returncode)


@test_app.command(
    "all",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def test_all(ctx: typer.Context) -> None:
    """Run the full test suite (Unit + Integration) sequentially."""
    env = os.environ.copy()
    extra_args = list(ctx.args)

    ui.show_panel("Starting Full Test Suite", border_style="magenta")

    # 1. Run Unit Tests
    try:
        _run_pytest_targets(
            ["tests/unit"],
            title="Unit Tests",
            extra_args=extra_args,
            env=env,
        )
    except typer.Exit:
        ui.show_error("Stopping suite due to unit test failure.")
        raise

    # 2. Run Integration Tests
    try:
        _run_pytest_targets(
            ["tests/integration"],
            title="Integration Tests",
            extra_args=extra_args,
            env=env,
        )
    except typer.Exit:
        raise

    ui.show_panel("All Tests Suites Completed Successfully", border_style="green")


@test_app.command(
    "integration",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def test_integration(ctx: typer.Context) -> None:
    """Run only integration tests."""
    env = os.environ.copy()
    _run_pytest_targets(
        ["tests/integration"],
        title="Integration tests",
        extra_args=list(ctx.args),
        env=env,
    )


@doctor_app.command("controller")
def doctor_controller() -> None:
    """Check controller-side requirements (Python deps, ansible-runner)."""
    failures = doctor_service.check_controller()
    if failures:
        raise typer.Exit(1)


@doctor_app.command("local-tools")
def doctor_local_tools() -> None:
    """Check local workload tools (only needed for local runs)."""
    failures = doctor_service.check_local_tools()
    if failures:
        raise typer.Exit(1)


@doctor_app.command("multipass")
def doctor_multipass() -> None:
    """Check if Multipass is installed (used by integration test)."""
    failures = doctor_service.check_multipass()
    if failures:
        raise typer.Exit(1)


@doctor_app.command("all")
def doctor_all() -> None:
    """Run all doctor checks."""
    failures = doctor_service.check_all()
    if failures:
        raise typer.Exit(1)


@app.command("tui")
def launch_tui(
    config: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Config file to load when launching the TUI."
    )
) -> None:
    """Notify users that the legacy Textual TUI has been removed."""
    ui.show_warning("The Textual TUI has been removed. Use the standard CLI commands instead.")


@app.command("hosts")
def show_hosts(config: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to BenchmarkConfig JSON file.")) -> None:
    """Display remote hosts configured in the provided config."""
    cfg = _load_config(config)
    if not cfg.remote_hosts:
        ui.show_warning("No remote hosts configured.")
        return

    rows = [
        [host.name, host.address, host.user, "yes" if host.become else "no"]
        for host in cfg.remote_hosts
    ]
    ui.show_table("Configured Remote Hosts", ["Name", "Address", "User", "Become"], rows)


@app.command("run")
def run_benchmarks(
    tests: Optional[List[str]] = typer.Argument(
        None,
        help="Workloads to run; default is all enabled workloads in the config.",
    ),
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to BenchmarkConfig JSON file."),
    run_id: Optional[str] = typer.Option(None, "--run-id", help="Override run identifier."),
    remote: Optional[bool] = typer.Option(
        None,
        "--remote/--no-remote",
        help="Force remote mode; default follows config.remote_execution.enabled.",
    ),
    docker: bool = typer.Option(
        False,
        "--docker/--no-docker",
        help="Execute via the container image instead of locally/remotely.",
    ),
    docker_image: str = typer.Option(
        "linux-benchmark-lib:dev",
        "--docker-image",
        help="Container image tag to build/use for --docker runs.",
    ),
    docker_engine: str = typer.Option(
        "docker",
        "--docker-engine",
        help="Container engine to use (docker or podman).",
    ),
    docker_no_cache: bool = typer.Option(
        False,
        "--docker-no-cache",
        help="Disable cache when building the container image.",
    ),
    docker_no_build: bool = typer.Option(
        False,
        "--docker-no-build",
        help="Skip building the image before running (assumes it already exists).",
    ),
) -> None:
    """Run selected workloads locally or via the remote controller."""
    resolved_cfg, _ = config_service.resolve_config_path(config)
    cfg = _load_config(config)
    context = run_service.build_context(
        cfg,
        tests,
        remote,
        docker=docker,
        docker_image=docker_image,
        docker_engine=docker_engine,
        docker_build=not docker_no_build,
        docker_no_cache=docker_no_cache,
        config_path=resolved_cfg,
    )
    if not context.use_remote and not context.use_container:
        available: list[str] = []
        skipped: list[str] = []
        for name in context.target_tests:
            workload = cfg.workloads.get(name)
            if workload is None:
                skipped.append(name)
                continue
            try:
                gen = context.registry.create_generator(workload.plugin, workload.options)
                # Use public API if available
                checker = getattr(gen, "check_prerequisites", None)
                if callable(checker):
                    can_run = checker()
                else:
                    # Fallback
                    validator = getattr(gen, "_validate_environment", None)
                    can_run = validator() if callable(validator) else True

                if can_run:
                    available.append(name)
                else:
                    skipped.append(name)
            except Exception:
                skipped.append(name)
        if skipped:
            skipped_list = ", ".join(sorted(skipped))
            ui.show_warning(f"Skipping workloads due to missing prerequisites: {skipped_list}")
        context.target_tests = available

    if context.use_container:
        # Ensure host-side artifact directory exists for bind mount
        cfg.ensure_output_dirs()
    if not context.target_tests:
        ui.show_warning("No workloads to run (none specified, enabled, or available).")
        raise typer.Exit(0)
    if context.use_remote and not cfg.remote_hosts:
        ui.show_error("Remote mode requested but no remote_hosts are configured.")
        raise typer.Exit(1)

    try:
        if context.use_remote:
            _print_run_plan(cfg, context.target_tests, registry=context.registry)
            if not cfg.remote_hosts:
                ui.show_error("Remote mode requested but no remote_hosts are configured.")
                raise typer.Exit(1)
            
            def console_callback(text: str, end: str = "\n") -> None:
                ui.show_info(text.rstrip("\n") + ("" if end == "" else end))

            result = run_service.execute(
                context,
                run_id=run_id,
                output_callback=console_callback,
                ui_adapter=ui,
            )
            summary = result.summary
            if summary is None:
                ui.show_error("Remote run failed to produce a summary.")
                raise typer.Exit(1)

            rows = []
            for phase, result in summary.phases.items():
                status_label = result.status
                if result.success:
                    status_label = f"{result.status} (ok)"
                rows.append([phase, status_label, str(result.rc)])
            ui.show_table("Run Summary", ["Phase", "Status", "RC"], rows)

            if summary.success:
                ui.show_panel(
                    f"Output: {summary.output_root}\nReports: {summary.report_root}\nExports: {summary.data_export_root}",
                    title="Success",
                    border_style="green",
                )
            else:
                ui.show_error("One or more phases failed.")
                raise typer.Exit(1)
        else:
            _print_run_plan(
                cfg, 
                context.target_tests, 
                registry=context.registry,
                docker_mode=context.use_container
            )
            run_service.execute(context, run_id=run_id, ui_adapter=ui)
            ui.show_panel("Local benchmarks completed.", border_style="green")
    except typer.Exit:
        raise
    except Exception as exc:  # pragma: no cover - runtime errors routed to user
        ui.show_error(f"Run failed: {exc}")
        raise typer.Exit(1)


if __name__ == "__main__":  # pragma: no cover
    app()
