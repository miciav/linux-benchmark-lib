"""
Command-line interface for linux-benchmark-lib.

Exposes quick commands to inspect plugins/hosts and run benchmarks locally or remotely.
"""

from __future__ import annotations

import os
import importlib
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from benchmark_config import BenchmarkConfig, RemoteHostConfig, WorkloadConfig
from controller import BenchmarkController
from local_runner import LocalRunner
from plugins.builtin import builtin_plugins
from plugins.registry import PluginRegistry, print_plugin_table


console = Console()
app = typer.Typer(help="Run linux-benchmark workloads locally or against remote hosts.")
config_app = typer.Typer(help="Manage benchmark configuration files.")
doctor_app = typer.Typer(help="Check local prerequisites.")
test_app = typer.Typer(help="Convenience helpers to run integration tests.")

CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "lb"
DEFAULT_CONFIG_NAME = "config.json"
DEFAULT_CONFIG_POINTER = CONFIG_HOME / "config_path"


def _ensure_config_home() -> None:
    CONFIG_HOME.mkdir(parents=True, exist_ok=True)


def _default_config_target() -> Path:
    return CONFIG_HOME / DEFAULT_CONFIG_NAME


def _read_saved_config_path() -> Tuple[Optional[Path], Optional[Path]]:
    """
    Return a saved default config path (if valid) and any stale path.

    Returns (valid_path, stale_path).
    """
    if not DEFAULT_CONFIG_POINTER.exists():
        return None, None

    raw = DEFAULT_CONFIG_POINTER.read_text().strip()
    if not raw:
        return None, None

    candidate = Path(raw).expanduser()
    if candidate.exists():
        return candidate, None
    return None, candidate


def _write_saved_config_path(path: Path) -> None:
    _ensure_config_home()
    DEFAULT_CONFIG_POINTER.write_text(str(path.expanduser()))


def _clear_saved_config_path() -> None:
    if DEFAULT_CONFIG_POINTER.exists():
        DEFAULT_CONFIG_POINTER.unlink()


def _resolve_config_path(config_path: Optional[Path]) -> Tuple[Optional[Path], Optional[Path]]:
    """Pick a config path using explicit input, saved default, or local file."""
    if config_path is not None:
        return Path(config_path).expanduser(), None

    saved, stale = _read_saved_config_path()
    if saved:
        return saved, None
    if stale:
        return None, stale

    local = Path("benchmark_config.json")
    if local.exists():
        return local, None
    return None, None


def _load_config(config_path: Optional[Path]) -> BenchmarkConfig:
    """Load a BenchmarkConfig from disk or fall back to defaults."""
    resolved, stale = _resolve_config_path(config_path)
    if stale:
        console.print(f"[yellow]Saved default config not found: {stale}[/yellow]")
    if resolved is None:
        console.print("[yellow]No config file found; using built-in defaults.[/yellow]")
        return BenchmarkConfig()

    try:
        cfg = BenchmarkConfig.load(resolved)
        console.print(f"[green]Loaded config:[/green] {resolved}")
        return cfg
    except Exception as exc:  # pragma: no cover - user input path
        console.print(f"[red]Failed to load config {resolved}: {exc}[/red]")
        raise typer.Exit(1)


def _load_config_for_write(
    config_path: Optional[Path],
    allow_create: bool = True,
) -> tuple[BenchmarkConfig, Path]:
    """
    Load config for mutation and return (config, target_path).

    Creates a new config at the default location when none exists and creation is allowed.
    """
    resolved, stale = _resolve_config_path(config_path)
    if stale:
        console.print(f"[yellow]Saved default config not found: {stale}[/yellow]")

    target = resolved or _default_config_target()
    created = False

    if target.exists():
        cfg = BenchmarkConfig.load(target)
        console.print(f"[green]Loaded config:[/green] {target}")
    else:
        if not allow_create:
            console.print(f"[red]Config file not found: {target}[/red]")
            raise typer.Exit(1)
        target.parent.mkdir(parents=True, exist_ok=True)
        cfg = BenchmarkConfig()
        created = True
        console.print(f"[yellow]Created new config at {target} using defaults.[/yellow]")

    return cfg, target


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
    target = Path(path).expanduser() if path else _default_config_target()
    target.parent.mkdir(parents=True, exist_ok=True)

    cfg = BenchmarkConfig()
    if interactive and typer.confirm("Configure a remote host now?", default=False):
        name = typer.prompt("Host name", default="node1")
        address = typer.prompt("Host address", default="192.168.1.10")
        user = typer.prompt("SSH user", default="ubuntu")
        key_path = typer.prompt(
            "SSH private key path",
            default=str(Path("~/.ssh/id_rsa").expanduser()),
        )
        become = typer.confirm("Use sudo (become)?", default=True)
        cfg.remote_hosts = [
            RemoteHostConfig(
                name=name,
                address=address,
                user=user,
                become=become,
                vars={
                    "ansible_ssh_private_key_file": key_path,
                    "ansible_ssh_common_args": "-o StrictHostKeyChecking=no",
                },
            )
        ]
        cfg.remote_execution.enabled = True

    cfg.save(target)
    console.print(f"[green]Config written to {target}[/green]")
    if set_default:
        _write_saved_config_path(target)
        console.print(f"[cyan]Default config set to {target}[/cyan]")


@config_app.command("set-default")
def config_set_default(
    path: Path = typer.Argument(..., help="Path to an existing BenchmarkConfig JSON file."),
) -> None:
    """Remember a config path as the CLI default."""
    target = Path(path).expanduser()
    if not target.exists():
        console.print(f"[red]Config file not found: {target}[/red]")
        raise typer.Exit(1)
    _write_saved_config_path(target)
    console.print(f"[green]Default config set to {target}[/green]")


@config_app.command("show-default")
def config_show_default() -> None:
    """Show the currently saved default config path."""
    saved, _ = _read_saved_config_path()
    if not saved:
        console.print("[yellow]No default config is set.[/yellow]")
        return
    console.print(f"[green]Default config:[/green] {saved}")


@config_app.command("unset-default")
def config_unset_default() -> None:
    """Clear the saved default config path."""
    _clear_saved_config_path()
    console.print("[green]Default config cleared.[/green]")


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
    resolved, stale = _resolve_config_path(path)
    if stale:
        console.print(f"[yellow]Saved default config not found: {stale}[/yellow]")
    if resolved is None:
        console.print("[red]No config file found to edit. Run `lb config init` first.[/red]")
        raise typer.Exit(1)

    editor = os.environ.get("EDITOR")
    if not editor:
        console.print(f"[red]Set $EDITOR or open the file manually: {resolved}[/red]")
        raise typer.Exit(1)

    try:
        subprocess.run([editor, str(resolved)], check=False)
    except Exception as exc:  # pragma: no cover - depends on user env
        console.print(f"[red]Failed to launch editor: {exc}[/red]")
        raise typer.Exit(1)


@config_app.command("workloads")
def config_list_workloads(
    config: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Config file to inspect."
    )
) -> None:
    """List workloads and their enabled status."""
    cfg = _load_config(config)
    table = Table(title="Configured Workloads", show_edge=False, header_style="bold cyan")
    table.add_column("Name", style="bold")
    table.add_column("Plugin")
    table.add_column("Enabled")

    for name, wl in sorted(cfg.workloads.items()):
        table.add_row(name, wl.plugin, "yes" if wl.enabled else "no")
    console.print(table)


def _update_workload_enabled(
    name: str,
    enabled: bool,
    config: Optional[Path],
    set_default: bool,
) -> tuple[BenchmarkConfig, Path]:
    cfg, target = _load_config_for_write(config, allow_create=True)
    workload = cfg.workloads.get(name) or WorkloadConfig(plugin=name, options={})
    workload.enabled = enabled
    cfg.workloads[name] = workload
    cfg.save(target)
    if set_default:
        _write_saved_config_path(target)
        console.print(f"[cyan]Default config set to {target}[/cyan]")
    console.print(
        f"[green]Workload '{name}' {'enabled' if enabled else 'disabled'} in {target}[/green]"
    )
    return cfg, target


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
    _update_workload_enabled(name, True, config, set_default)


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
    _update_workload_enabled(name, False, config, set_default)


app.add_typer(config_app, name="config")
app.add_typer(doctor_app, name="doctor")
app.add_typer(test_app, name="test")


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
) -> None:
    """Show available workload plugins (built-ins and entry points)."""
    registry = PluginRegistry(builtin_plugins())
    if not registry.available():
        console.print("[yellow]No workload plugins registered.[/yellow]")
        return

    if enable and disable:
        console.print("[red]Choose either --enable or --disable, not both.[/red]")
        raise typer.Exit(1)

    cfg_for_table: Optional[BenchmarkConfig] = None
    if enable:
        cfg_for_table, _ = _update_workload_enabled(enable, True, config, set_default)
    if disable:
        cfg_for_table, _ = _update_workload_enabled(disable, False, config, set_default)
    if cfg_for_table is None:
        cfg_for_table = _load_config(config)

    enabled_map = {name: wl.enabled for name, wl in cfg_for_table.workloads.items()}
    print_plugin_table(registry, enabled=enabled_map)


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
) -> None:
    """
    Run the Multipass integration test via pytest.

    Requires multipass + ansible/ansible-runner installed locally.
    """
    if not _check_command("multipass"):
        console.print("[red]multipass not found in PATH; install it to run this test.[/red]")
        raise typer.Exit(1)
    if not _check_import("ansible_runner"):
        console.print("[red]ansible-runner python package not available.[/red]")
        raise typer.Exit(1)
    if not _check_command("ansible-playbook"):
        console.print("[red]ansible-playbook not available in PATH.[/red]")
        raise typer.Exit(1)

    artifacts_dir = artifacts_dir.expanduser().resolve()
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["LB_TEST_RESULTS_DIR"] = str(artifacts_dir)
    # Propagate standard env (ANSIBLE_ROLES_PATH/ANSIBLE_CONFIG are set in test)
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "tests/integration/test_multipass_benchmark.py",
    ]
    extra_args = list(ctx.args)
    if extra_args:
        cmd.extend(extra_args)

    summary = Table(title="Multipass Integration Plan", show_edge=False, header_style="bold cyan")
    summary.add_column("Field", style="bold")
    summary.add_column("Value")
    summary.add_row("Pytest target", "tests/integration/test_multipass_benchmark.py")
    summary.add_row("Iterations", "1 (pytest invocation)")
    summary.add_row("Workload", "stress_ng")
    summary.add_row("Duration", "5s (warmup 0s, cooldown 0s)")
    summary.add_row("Artifacts dir", str(artifacts_dir))
    summary.add_row("Extra args", " ".join(extra_args) if extra_args else "None")
    summary.add_row("Config source", "Embedded in test (not user config)")
    console.print(summary)

    workload_table = Table(title="Workload Parameters", show_edge=False, header_style="bold cyan")
    workload_table.add_column("Workload", style="bold")
    workload_table.add_column("Duration")
    workload_table.add_column("Repetitions")
    workload_table.add_column("Warmup/Cooldown")
    workload_table.add_column("Notes")
    workload_table.add_row(
        "stress_ng",
        "5s",
        "1",
        "0s/0s",
        "timeout=5s, cpu_workers=1",
    )
    console.print(workload_table)

    try:
        with console.status(
            "[cyan]Running Multipass integration test (this can take a few minutes)...[/cyan]",
            spinner="dots",
        ):
            subprocess.run(cmd, check=True, env=env)
    except subprocess.CalledProcessError as exc:
        console.print(f"[red]Integration test failed with exit code {exc.returncode}[/red]")
        raise typer.Exit(exc.returncode)

    console.print(
        Panel.fit(
            f"Artifacts saved to: {artifacts_dir}\nCommand: {' '.join(cmd)}",
            title="Integration test completed",
            border_style="green",
        )
    )


def _run_pytest_targets(
    targets: List[str],
    title: str,
    extra_args: Optional[List[str]] = None,
    env: Optional[dict] = None,
) -> None:
    """Execute pytest against the given targets with friendly console output."""
    cmd = [sys.executable, "-m", "pytest"]
    cmd.extend(targets)
    if extra_args:
        cmd.extend(extra_args)

    summary = Table(title=title, show_edge=False, header_style="bold cyan")
    summary.add_column("Field", style="bold")
    summary.add_column("Value")
    summary.add_row("Pytest target", " ".join(targets))
    summary.add_row("Extra args", " ".join(extra_args) if extra_args else "None")
    console.print(summary)

    try:
        with console.status(
            f"[cyan]Running {title.lower()}...[/cyan]",
            spinner="dots",
        ):
            subprocess.run(cmd, check=True, env=env)
    except subprocess.CalledProcessError as exc:
        console.print(f"[red]Pytest failed with exit code {exc.returncode}[/red]")
        raise typer.Exit(exc.returncode)

    console.print(
        Panel.fit(
            f"Command: {' '.join(cmd)}",
            title=f"{title} completed",
            border_style="green",
        )
    )


@test_app.command(
    "all",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def test_all(ctx: typer.Context) -> None:
    """Run the full test suite (unit + integration)."""
    env = os.environ.copy()
    _run_pytest_targets(
        ["tests"],
        title="Full test suite",
        extra_args=list(ctx.args),
        env=env,
    )


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


def _check_import(name: str) -> bool:
    try:
        importlib.import_module(name)
        return True
    except Exception:
        return False


def _check_command(name: str) -> bool:
    return shutil.which(name) is not None


def _render_check_table(title: str, items: List[tuple[str, bool, bool]]) -> int:
    table = Table(title=title, show_edge=False, header_style="bold cyan")
    table.add_column("Item", style="bold")
    table.add_column("Status")
    failures = 0
    for label, ok, required in items:
        table.add_row(label, "[green]✓[/green]" if ok else "[red]✗[/red]")
        failures += 0 if ok or not required else 1
    console.print(table)
    return failures


@doctor_app.command("controller")
def doctor_controller() -> None:
    """Check controller-side requirements (Python deps, ansible-runner)."""
    failures = 0
    py_deps = [
        ("psutil", _check_import("psutil"), True),
        ("pandas", _check_import("pandas"), True),
        ("numpy", _check_import("numpy"), True),
        ("matplotlib", _check_import("matplotlib"), True),
        ("seaborn", _check_import("seaborn"), True),
        ("iperf3 (python)", _check_import("iperf3"), True),
        ("jc", _check_import("jc"), True),
        ("influxdb-client (optional)", _check_import("influxdb_client"), False),
    ]
    failures += _render_check_table("Python Dependencies", py_deps)

    controller_tools = [
        ("ansible-runner (python)", _check_import("ansible_runner"), True),
        ("ansible-playbook", _check_command("ansible-playbook"), True),
    ]
    failures += _render_check_table("Controller Tools", controller_tools)

    resolved, stale = _resolve_config_path(None)
    cfg_items = [
        ("Active config", resolved is not None, False),
        ("Stale default path", stale is None, False),
    ]
    failures += _render_check_table("Config Resolution", cfg_items)

    console.print(
        f"Python: {platform.python_version()} ({platform.python_implementation()}) on {platform.system()} {platform.release()}"
    )
    if failures:
        raise typer.Exit(1)


@doctor_app.command("local-tools")
def doctor_local_tools() -> None:
    """Check local workload tools (only needed for local runs)."""
    tools = ["stress-ng", "iperf3", "fio", "sar", "vmstat", "iostat", "mpstat", "pidstat", "perf"]
    items = [(cmd, _check_command(cmd), True) for cmd in tools]
    failures = _render_check_table("Local Workload Tools", items)
    if failures:
        raise typer.Exit(1)


@doctor_app.command("multipass")
def doctor_multipass() -> None:
    """Check if Multipass is installed (used by integration test)."""
    items = [("multipass", _check_command("multipass"), True)]
    failures = _render_check_table("Multipass", items)
    if failures:
        raise typer.Exit(1)


@doctor_app.command("all")
def doctor_all() -> None:
    """Run all doctor checks."""
    failures = 0
    try:
        doctor_controller()
    except typer.Exit:
        failures += 1
    try:
        doctor_local_tools()
    except typer.Exit:
        failures += 1
    try:
        doctor_multipass()
    except typer.Exit:
        failures += 1
    if failures:
        raise typer.Exit(1)


@app.command("hosts")
def show_hosts(config: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to BenchmarkConfig JSON file.")) -> None:
    """Display remote hosts configured in the provided config."""
    cfg = _load_config(config)
    if not cfg.remote_hosts:
        console.print("[yellow]No remote hosts configured.[/yellow]")
        return

    table = Table(title="Configured Remote Hosts", show_edge=False, header_style="bold cyan")
    table.add_column("Name", style="bold")
    table.add_column("Address")
    table.add_column("User")
    table.add_column("Become")

    for host in cfg.remote_hosts:
        table.add_row(host.name, host.address, host.user, "yes" if host.become else "no")

    console.print(table)


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
) -> None:
    """Run selected workloads locally or via the remote controller."""
    cfg = _load_config(config)
    target_tests = tests or [
        name for name, workload in cfg.workloads.items() if workload.enabled
    ]

    if not target_tests:
        console.print("[yellow]No workloads to run (none specified or enabled).[/yellow]")
        raise typer.Exit(0)

    use_remote = remote if remote is not None else cfg.remote_execution.enabled

    try:
        if use_remote:
            if not cfg.remote_hosts:
                console.print("[red]Remote mode requested but no remote_hosts are configured.[/red]")
                raise typer.Exit(1)
            controller = BenchmarkController(cfg)
            summary = controller.run(target_tests, run_id=run_id)

            table = Table(title="Run Summary", show_edge=False, header_style="bold cyan")
            table.add_column("Phase", style="bold")
            table.add_column("Status")
            table.add_column("RC")
            for phase, result in summary.phases.items():
                status_color = "green" if result.success else "red"
                table.add_row(phase, f"[{status_color}]{result.status}[/{status_color}]", str(result.rc))
            console.print(table)

            if summary.success:
                console.print(
                    Panel.fit(
                        f"Output: {summary.output_root}\nReports: {summary.report_root}\nExports: {summary.data_export_root}",
                        title="Success",
                        border_style="green",
                    )
                )
            else:
                console.print("[red]One or more phases failed.[/red]")
                raise typer.Exit(1)
        else:
            registry = PluginRegistry(builtin_plugins())
            runner = LocalRunner(cfg, registry=registry)
            for test_name in target_tests:
                runner.run_benchmark(test_name)
            console.print(Panel.fit("Local benchmarks completed.", border_style="green"))
    except typer.Exit:
        raise
    except Exception as exc:  # pragma: no cover - runtime errors routed to user
        console.print(f"[red]Run failed: {exc}[/red]")
        raise typer.Exit(1)


if __name__ == "__main__":  # pragma: no cover
    app()
