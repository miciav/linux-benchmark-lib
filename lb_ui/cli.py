"""
Command-line interface for linux-benchmark-lib.

Exposes quick commands to inspect plugins/hosts and run benchmarks via provisioned environments (remote, Docker, Multipass).
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Dict, List, Optional, Set

import typer

from lb_provisioner import (
    MAX_NODES,
    ProvisioningError,
    ProvisioningMode,
    ProvisioningRequest,
    ProvisioningService,
)
from lb_controller.journal import RunJournal
from lb_controller.contracts import BenchmarkConfig, RemoteHostConfig, WorkloadConfig, RemoteExecutionConfig, PluginRegistry
from lb_controller.services import ConfigService, RunCatalogService, RunService
from lb_ui.services.analytics_service import AnalyticsRequest, AnalyticsService
from lb_controller.services.plugin_service import build_plugin_table, create_registry, PluginInstaller
from lb_controller.services.doctor_service import DoctorService
from lb_controller.services.doctor_types import DoctorReport
from lb_controller.services.test_service import TestService
from lb_controller.ui_interfaces import UIAdapter
from lb_ui.ui import viewmodels

# New UI System Imports
from lb_ui.ui.system.protocols import UI
from lb_ui.ui.system.facade import TUI
from lb_ui.ui.system.models import TableModel, PickItem
from lb_ui.ui.adapters.tui_adapter import TUIAdapter

# Initialize UI
ui: UI = TUI()
ui_adapter: UIAdapter = TUIAdapter(ui)

app = typer.Typer(help="Run linux-benchmark workloads on provisioned hosts (remote, Docker, Multipass).", no_args_is_help=True)
config_app = typer.Typer(help="Manage benchmark configuration files.", no_args_is_help=True)
doctor_app = typer.Typer(help="Check local prerequisites.", no_args_is_help=True)
test_app = typer.Typer(help="Convenience helpers to run integration tests.", no_args_is_help=True)
plugin_app = typer.Typer(help="Inspect and manage workload plugins.", no_args_is_help=False)
runs_app = typer.Typer(help="Inspect past benchmark runs.", no_args_is_help=True)

_CLI_ROOT = Path(__file__).resolve().parent.parent
_DEV_MARKER = _CLI_ROOT / ".lb_dev_cli"


def _load_dev_mode() -> bool:
    """Return True when dev mode is enabled via marker file or pyproject flag."""
    if _DEV_MARKER.exists():
        return True
    pyproject = _CLI_ROOT / "pyproject.toml"
    if pyproject.exists():
        try:
            data = tomllib.loads(pyproject.read_text())
            tool_cfg = data.get("tool", {}).get("lb_ui", {}) or {}
            if isinstance(tool_cfg, dict):
                dev_flag = tool_cfg.get("dev_mode")
                if isinstance(dev_flag, bool):
                    return dev_flag
        except Exception:
            pass
    return False


DEV_MODE = _load_dev_mode()
TEST_CLI_ENABLED = bool(os.environ.get("LB_ENABLE_TEST_CLI")) or DEV_MODE

config_service = ConfigService()
run_service = RunService(registry_factory=create_registry)
doctor_service = DoctorService(config_service=config_service)
test_service = TestService()
analytics_service = AnalyticsService()


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
    if headless:
        from lb_ui.ui.system.headless import HeadlessUI
        ui = HeadlessUI()
        ui_adapter = TUIAdapter(ui)
        # Re-inject if necessary, but services now mostly return data or use ui_adapter passed in methods (RunService)

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
    execution_mode: str = "remote",
) -> None:
    """Render a compact table of the workloads about to run with availability hints."""
    plan = run_service.get_run_plan(
        cfg,
        tests,
        execution_mode=execution_mode,
        registry=registry or create_registry(),
    )

    rows = [
        [
            item["name"],
            item["plugin"],
            item["intensity"],
            item["details"],
            item.get("repetitions", ""),
            item["status"],
        ]
        for item in plan
    ]
    ui.tables.show(TableModel(
        title="Run Plan",
        columns=["Workload", "Plugin", "Intensity", "Configuration", "Repetitions", "Status"],
        rows=rows,
    ))


def _build_journal_summary(journal: RunJournal) -> tuple[list[str], list[list[str]]]:
    """Return column headers and rows for a run journal snapshot."""
    return viewmodels.journal_rows(journal)


def _print_run_journal_summary(
    journal_path: Path,
    log_path: Path | None = None,
    ui_log_path: Path | None = None,
) -> None:
    """Load and render a completed run journal, with log hints."""
    try:
        journal = RunJournal.load(journal_path)
    except Exception as exc:
        ui.present.warning(f"Could not read run journal at {journal_path}: {exc}")
        if log_path:
            ui.present.info(f"Ansible output log: {log_path}")
        return

    columns, rows = _build_journal_summary(journal)
    if rows:
        ui.tables.show(TableModel(title=f"Run Journal (ID: {journal.run_id})", columns=columns, rows=rows))
    else:
        ui.present.warning("Run journal was created but contains no tasks.")

    ui.present.info(f"Journal saved to {journal_path}")
    if log_path:
        ui.present.info(f"Ansible output log saved to {log_path}")
    if ui_log_path:
        ui.present.info(f"Dashboard log stream saved to {ui_log_path}")


def _cleanup_provisioned_nodes(provisioning_result, result, presenter) -> None:
    """Apply cleanup policy using controller authorization."""
    if not provisioning_result:
        return
    allow_cleanup = bool(
        result and result.summary and result.summary.cleanup_allowed
    )
    if result and result.summary and not result.summary.success:
        presenter.warning("Run failed; preserving provisioned nodes for inspection.")
        provisioning_result.keep_nodes = True
    if not allow_cleanup:
        presenter.warning("Controller did not authorize cleanup; provisioned nodes preserved.")
        provisioning_result.keep_nodes = True
    provisioning_result.destroy_all()


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
        ui.present.error(str(exc))
        raise typer.Exit(1)


def _load_config(config_path: Optional[Path]) -> BenchmarkConfig:
    """Load a BenchmarkConfig from disk or fall back to defaults."""
    cfg, resolved, stale = config_service.load_for_read(config_path)
    if stale:
        ui.present.warning(f"Saved default config not found: {stale}")
    if resolved is None:
        ui.present.warning("No config file found; using built-in defaults.")
        return cfg

    ui.present.success(f"Loaded config: {resolved}")
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
    repetitions: int = typer.Option(
        3,
        "--repetitions",
        "-r",
        help="Number of repetitions to run for each workload (must be >= 1).",
    ),
) -> None:
    """Create a config file from defaults and optionally set it as default."""
    target = Path(path).expanduser() if path else config_service.default_target
    target.parent.mkdir(parents=True, exist_ok=True)

    if repetitions < 1:
        ui.present.error("Repetitions must be at least 1.")
        raise typer.Exit(1)

    cfg = config_service.create_default_config()
    cfg.repetitions = repetitions
    if interactive:
        ui.present.info("Configure remote host")
        name = ui.form.ask("Host name", default="node1")
        address = ui.form.ask("Host address", default="192.168.1.10")
        user = ui.form.ask("SSH user", default="ubuntu")
        key_path = ui.form.ask("SSH private key path", default="~/.ssh/id_rsa")
        become = ui.form.confirm("Use sudo (become)?", default=True)
        
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
    ui.present.success(f"Config written to {target}")
    if set_default:
        config_service.write_saved_config_path(target)
        ui.present.info(f"Default config set to {target}")


@config_app.command("set-repetitions")
def config_set_repetitions(
    repetitions: int = typer.Argument(..., help="Number of repetitions to store in the config."),
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Config file to update."),
    set_default: bool = typer.Option(
        False,
        "--set-default/--no-set-default",
        help="Remember this config as the default.",
    ),
) -> None:
    """Persist the desired repetitions count to the configuration file."""

    if repetitions < 1:
        ui.present.error("Repetitions must be at least 1.")
        raise typer.Exit(1)

    cfg, target, stale, _ = config_service.load_for_write(config, allow_create=True)
    cfg.repetitions = repetitions
    cfg.save(target)

    if set_default:
        config_service.write_saved_config_path(target)

    if stale:
        ui.present.warning(f"Saved default config not found: {stale}")
    ui.present.success(f"Repetitions set to {repetitions} in {target}")


@config_app.command("set-default")
def config_set_default(
    path: Path = typer.Argument(..., help="Path to an existing BenchmarkConfig JSON file."),
) -> None:
    """Remember a config path as the CLI default."""
    target = Path(path).expanduser()
    if not target.exists():
        ui.present.error(f"Config file not found: {target}")
        raise typer.Exit(1)
    config_service.write_saved_config_path(target)
    ui.present.success(f"Default config set to {target}")


@config_app.command("show-default")
def config_show_default() -> None:
    """Show the currently saved default config path."""
    saved, _ = config_service.read_saved_config_path()
    if not saved:
        ui.present.warning("No default config is set.")
        return
    ui.present.success(f"Default config: {saved}")


@config_app.command("unset-default")
def config_unset_default() -> None:
    """Clear the saved default config path."""
    config_service.clear_saved_config_path()
    ui.present.success("Default config cleared.")


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
    ui.tables.show(TableModel(title="Configured Workloads", columns=["Name", "Plugin", "Enabled"], rows=rows))
    # Plain text echo for pipe-ability if needed (optional, keeping consistent with old CLI if desired, but prompt said "No print... outside UI layer")
    # I'll rely on TableModel mostly.


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
            ui.present.warning(f"Saved default config not found: {stale}")
        ui.present.success(f"Workload '{name}' enabled in {target}")
    except ValueError as e:
        ui.present.error(str(e))
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
        ui.present.warning(f"Saved default config not found: {stale}")
    ui.present.success(f"Workload '{name}' disabled in {target}")


def _select_workloads_interactively(
    cfg: BenchmarkConfig,
    registry: PluginRegistry,
    config: Optional[Path],
    set_default: bool,
) -> None:
    """Interactively toggle configured workloads using arrows + space."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        ui.present.error("Interactive selection requires a TTY.")
        raise typer.Exit(1)

    available_plugins = registry.available()
    items = []

    intensities_catalog = [
        PickItem(id="user_defined", title="user_defined", description="Custom intensity"),
        PickItem(id="low", title="low", description="Light load"),
        PickItem(id="medium", title="medium", description="Balanced load"),
        PickItem(id="high", title="high", description="Aggressive load"),
    ]

    # Prepare items for picker with variants as intensities
    for name, wl in sorted(cfg.workloads.items()):
        plugin_obj = available_plugins.get(wl.plugin)
        description = getattr(plugin_obj, "description", "") if plugin_obj else ""
        current_intensity = wl.intensity if wl.intensity else "user_defined"
        variant_list = []
        for variant in intensities_catalog:
            label = variant.title
            desc = variant.description
            if variant.id == current_intensity:
                desc = f"(current) {desc}"
            variant_list.append(
                PickItem(
                    id=variant.id,
                    title=label,
                    description=desc,
                    payload=variant.payload,
                    tags=variant.tags,
                    search_blob=variant.search_blob or label,
                    preview=variant.preview,
                )
            )

        item = PickItem(
            id=name,
            title=name,
            description=f"Plugin: {wl.plugin} | Intensity: {current_intensity} | {description}",
            payload=wl,
            variants=variant_list,
            search_blob=f"{name} {wl.plugin} {description}",
        )
        items.append(item)

    selection = ui.picker.pick_many(items, title="Select Configured Workloads")
    selected_names = set()
    intensities: Dict[str, str] = {}

    for picked in selection:
        # Variants come back as "<workload>:<intensity>"
        if ":" in picked.id:
            base, level = picked.id.split(":", 1)
            selected_names.add(base)
            intensities[base] = level
        else:
            selected_names.add(picked.id)

    if not selection:
        ui.present.warning("Selection cancelled or empty.")
        if not ui.form.confirm("Do you want to proceed with NO workloads enabled?", default=False):
            raise typer.Exit(1)

    cfg_write, target, stale, _ = config_service.load_for_write(config, allow_create=True)
    for name, wl in cfg_write.workloads.items():
        wl.enabled = name in selected_names
        if wl.enabled and name in intensities:
            wl.intensity = intensities[name]
        cfg_write.workloads[name] = wl
    cfg_write.save(target)
    if set_default:
        config_service.write_saved_config_path(target)
    if stale:
        ui.present.warning(f"Saved default config not found: {stale}")
    ui.present.success(f"Workload selection saved to {target}")


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
        ui.present.warning("No workloads configured yet. Enable plugins first with `lb plugin list --enable NAME`.")
        return

    registry = create_registry()
    _select_workloads_interactively(cfg, registry, config, set_default)


def _render_doctor_report(report: DoctorReport) -> None:
    for group in report.groups:
        rows = [[item.label, "✓" if item.ok else "✗"] for item in group.items]
        ui.tables.show(TableModel(title=group.title, columns=["Item", "Status"], rows=rows))
    
    for msg in report.info_messages:
        ui.present.info(msg)
        
    if report.total_failures > 0:
        ui.present.error(f"Found {report.total_failures} failures.")
    else:
        ui.present.success("All checks passed.")


@doctor_app.callback(invoke_without_command=True)
def doctor_root(ctx: typer.Context) -> None:
    """Check environment health and prerequisites."""
    if ctx.invoked_subcommand is None:
        report = doctor_service.check_all()
        _render_doctor_report(report)
        if report.total_failures > 0:
            raise typer.Exit(1)


@doctor_app.command("all")
def doctor_all() -> None:
    """Run all checks."""
    report = doctor_service.check_all()
    _render_doctor_report(report)
    if report.total_failures > 0:
        raise typer.Exit(1)


@doctor_app.command("controller")
def doctor_controller() -> None:
    """Check controller prerequisites (Ansible, Python deps)."""
    report = doctor_service.check_controller()
    _render_doctor_report(report)
    if report.total_failures > 0:
        raise typer.Exit(1)


@doctor_app.command("local")
def doctor_local() -> None:
    """Check local workload tools (stress-ng, fio, etc)."""
    report = doctor_service.check_local_tools()
    _render_doctor_report(report)
    if report.total_failures > 0:
        raise typer.Exit(1)


@doctor_app.command("multipass")
def doctor_multipass() -> None:
    """Check Multipass installation."""
    report = doctor_service.check_multipass()
    _render_doctor_report(report)
    if report.total_failures > 0:
        raise typer.Exit(1)


@runs_app.command("list")
def runs_list(
    root: Optional[Path] = typer.Option(
        None,
        "--root",
        "-r",
        help="Root directory containing benchmark_results run folders.",
    ),
    config: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Config file to infer output/report/export roots.",
    ),
) -> None:
    """List available benchmark runs."""
    cfg, _, _ = config_service.load_for_read(config)
    output_root = root or cfg.output_dir
    catalog = RunCatalogService(
        output_dir=output_root,
        report_dir=cfg.report_dir,
        data_export_dir=cfg.data_export_dir,
    )
    runs = catalog.list_runs()
    if not runs:
        ui.present.warning(f"No runs found under {output_root}")
        return
    rows: List[List[str]] = []
    for run in runs:
        created = run.created_at.isoformat() if run.created_at else "-"
        hosts = ", ".join(run.hosts) if run.hosts else "-"
        workloads = ", ".join(run.workloads) if run.workloads else "-"
        rows.append([run.run_id, created, hosts, workloads])
    ui.tables.show(TableModel(title="Benchmark Runs", columns=["Run ID", "Created", "Hosts", "Workloads"], rows=rows))


@runs_app.command("show")
def runs_show(
    run_id: str = typer.Argument(..., help="Run identifier (folder name)."),
    root: Optional[Path] = typer.Option(
        None,
        "--root",
        "-r",
        help="Root directory containing benchmark_results run folders.",
    ),
    config: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Config file to infer output/report/export roots.",
    ),
) -> None:
    """Show details for a single run."""
    cfg, _, _ = config_service.load_for_read(config)
    output_root = root or cfg.output_dir
    catalog = RunCatalogService(
        output_dir=output_root,
        report_dir=cfg.report_dir,
        data_export_dir=cfg.data_export_dir,
    )
    run = catalog.get_run(run_id)
    if not run:
        ui.present.error(f"Run '{run_id}' not found under {output_root}")
        raise typer.Exit(1)
    rows = [
        ["Run ID", run.run_id],
        ["Output", str(run.output_root)],
        ["Reports", str(run.report_root or "-")],
        ["Exports", str(run.data_export_root or "-")],
        ["Created", run.created_at.isoformat() if run.created_at else "-"],
        ["Hosts", ", ".join(run.hosts) if run.hosts else "-"],
        ["Workloads", ", ".join(run.workloads) if run.workloads else "-"],
        ["Journal", str(run.journal_path or "-")],
    ]
    ui.tables.show(TableModel(title="Run Details", columns=["Field", "Value"], rows=rows))


@app.command("analyze")
def analyze(
    run_id: Optional[str] = typer.Argument(
        None, help="Run identifier (folder name). If omitted, prompt to select."
    ),
    kind: Optional[str] = typer.Option(
        None,
        "--kind",
        "-k",
        help="Analytics kind to run (currently: aggregate).",
    ),
    root: Optional[Path] = typer.Option(
        None,
        "--root",
        "-r",
        help="Root directory containing benchmark_results run folders.",
    ),
    workload: Optional[List[str]] = typer.Option(
        None,
        "--workload",
        "-w",
        help="Workload(s) to analyze (repeatable). Default: all in run.",
    ),
    host: Optional[List[str]] = typer.Option(
        None,
        "--host",
        "-H",
        help="Host(s) to analyze (repeatable). Default: all in run.",
    ),
    config: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Config file to infer output/report/export roots.",
    ),
) -> None:
    """Run analytics on an existing benchmark run."""
    cfg, _, _ = config_service.load_for_read(config)
    output_root = root or cfg.output_dir
    catalog = RunCatalogService(
        output_dir=output_root,
        report_dir=cfg.report_dir,
        data_export_dir=cfg.data_export_dir,
    )

    selected_run_id = run_id
    if selected_run_id is None:
        runs = catalog.list_runs()
        if not runs:
            ui.present.error(f"No runs found under {output_root}")
            raise typer.Exit(1)
            
        items = [PickItem(id=r.run_id, title=f"{r.run_id} ({r.created_at})") for r in runs]
        selection = ui.picker.pick_one(items, title="Select a benchmark run")
        selected_run_id = selection.id if selection else runs[0].run_id
        ui.present.info(f"Selected run: {selected_run_id}")

    run = catalog.get_run(selected_run_id)
    if not run:
        ui.present.error(f"Run '{selected_run_id}' not found under {output_root}")
        raise typer.Exit(1)

    selected_kind = kind
    if not selected_kind:
        k_items = [PickItem(id="aggregate", title="aggregate")]
        k_sel = ui.picker.pick_one(k_items, title="Select analytics type", query_hint="aggregate")
        selected_kind = k_sel.id if k_sel else "aggregate"
        
    if selected_kind != "aggregate":
        ui.present.error(f"Unsupported analytics kind: {selected_kind}")
        raise typer.Exit(1)

    selected_workloads = workload
    if selected_workloads is None:
        # Multi select workloads
        w_items = [PickItem(id=w, title=w) for w in list(run.workloads)]
        w_sel = ui.picker.pick_many(w_items, title="Select workloads to analyze")
        selected_workloads = sorted([s.id for s in w_sel]) if w_sel else None

    selected_hosts = host
    if selected_hosts is None:
        h_items = [PickItem(id=h, title=h) for h in list(run.hosts)]
        h_sel = ui.picker.pick_many(h_items, title="Select hosts to analyze")
        selected_hosts = sorted([s.id for s in h_sel]) if h_sel else None

    req = AnalyticsRequest(
        run=run,
        kind="aggregate",
        hosts=selected_hosts,
        workloads=selected_workloads,
    )
    with ui.progress.status(f"Running analytics '{selected_kind}' on {run.run_id}"):
        produced = analytics_service.run(req)
    if not produced:
        ui.present.warning("No analytics artifacts produced.")
        return
    rows = [[str(p)] for p in produced]
    ui.tables.show(TableModel(title="Analytics Artifacts", columns=["Path"], rows=rows))
    ui.present.success("Analytics completed.")


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
        ui.present.error("multipass not found in PATH.")
        raise typer.Exit(1)
    if not _check_import("pytest"):
        ui.present.error("pytest is not installed.")
        raise typer.Exit(1)

    output = output.expanduser()
    output.mkdir(parents=True, exist_ok=True)

    # Multipass selection logic moved here
    default_level = "medium"
    scenario_choice = "stress_ng"
    level = default_level

    if multi_workloads:
        scenario_choice = "multi"
    else:
        # Use TUI
        cfg_preview = ConfigService().create_default_config().workloads
        names = sorted(cfg_preview.keys())
        options = list(dict.fromkeys(names + ["multi"]).keys())
        
        # Hierarchical construction for Master-Detail selection
        items = []
        for opt in options:
            variants = []
            for l in ["low", "medium", "high"]:
                variants.append(PickItem(id=f"{opt}:{l}", title=l))
            
            items.append(PickItem(id=opt, title=opt, variants=variants, description=f"Run {opt} scenario"))

        selection = ui.picker.pick_one(items, title="Select Multipass Scenario & Intensity")
        if selection:
            # If a variant was selected, its ID is combined "scenario:intensity"
            if ":" in selection.id:
                scenario_choice, level = selection.id.split(":")
            else:
                # Fallback if parent selected without variant (shouldn't happen with new logic, but robust)
                scenario_choice = selection.id
                level = default_level
                
            ui.present.success(f"Selected: {scenario_choice} @ {level}")
        else:
            ui.present.info(f"Using default: {scenario_choice} @ {level}")

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
    ui.present.info(f"VM count: {vm_count} ({label})")
    ui.present.info(f"Scenario: {scenario.workload_label} -> {scenario.target_label}")
    ui.present.info(f"Artifacts: {output}")

    try:
        result = subprocess.run(cmd, check=False, env=env)
    except Exception as exc:
        ui.present.error(f"Failed to launch Multipass test: {exc}")
        raise typer.Exit(1)

    if result.returncode != 0:
        ui.present.error(f"`pytest` exited with {result.returncode}")
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
        help="Override remote execution from the config (local mode is not supported).",
    ),
    docker: bool = typer.Option(
        False,
        "--docker",
        help="Provision containers (Ubuntu 24.04) and run via Ansible.",
    ),
    docker_engine: str = typer.Option(
        "docker",
        "--docker-engine",
        help="Container engine to use with --docker (docker or podman).",
    ),
    repetitions: Optional[int] = typer.Option(
        None,
        "--repetitions",
        "-r",
        help="Override the number of repetitions for this run (must be >= 1).",
    ),
    multipass: bool = typer.Option(
        False,
        "--multipass",
        help="Provision Multipass VMs (Ubuntu 24.04) and run benchmarks on them.",
    ),
    node_count: int = typer.Option(
        1,
        "--nodes",
        "--multipass-vm-count",
        help="Number of containers/VMs to provision (max 2).",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Enable verbose debug logging (sets fio.debug=True when applicable).",
    ),
    stop_file: Optional[Path] = typer.Option(
        None,
        "--stop-file",
        help="Path to a stop sentinel file; when created, the run will stop gracefully.",
    ),
    intensity: str = typer.Option(
        None,
        "--intensity",
        "-i",
        help="Override workload intensity (low, medium, high, user_defined).",
    ),
    setup: bool = typer.Option(
        True,
        "--setup/--no-setup",
        help="Run environment setup (Global + Workload) before execution.",
    ),
) -> None:
    """Run workloads using Ansible on remote, Docker, or Multipass targets."""
    if not DEV_MODE and (docker or multipass):
        ui.present.error("--docker and --multipass are available only in dev mode.")
        raise typer.Exit(1)

    if docker and multipass:
        ui.present.error("Choose either --docker or --multipass, not both.")
        raise typer.Exit(1)

    if remote is False and not docker and not multipass:
        ui.present.error(
            "Local execution has been removed; enable --remote, --docker, or --multipass."
        )
        raise typer.Exit(1)

    if debug:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            force=True,
        )
        ui.present.info("Debug logging enabled")

    if node_count < 1:
        ui.present.error("Node count must be at least 1.")
        raise typer.Exit(1)
    if node_count > MAX_NODES:
        ui.present.error(f"Maximum supported nodes is {MAX_NODES}.")
        raise typer.Exit(1)

    if repetitions is not None and repetitions < 1:
        ui.present.error("Repetitions must be at least 1.")
        raise typer.Exit(1)

    stop_file = stop_file or (
        Path(os.environ["LB_STOP_FILE"])
        if os.environ.get("LB_STOP_FILE")
        else None
    )

    cfg, resolved, stale = config_service.load_for_read(config)
    if stale:
        ui.present.warning(f"Saved default config not found: {stale}")
    if resolved:
        ui.present.success(f"Loaded config: {resolved}")
    else:
        ui.present.warning("No config file found; using built-in defaults.")

    cfg.ensure_output_dirs()

    execution_mode = (
        ProvisioningMode.DOCKER
        if docker
        else ProvisioningMode.MULTIPASS
        if multipass
        else ProvisioningMode.REMOTE
    )

    provisioner = ProvisioningService()
    provisioning_result = None

    try:
        if execution_mode is ProvisioningMode.REMOTE:
            if remote is False:
                raise ValueError(
                    "Remote execution is required; use --docker or --multipass instead."
                )
            if not cfg.remote_hosts:
                raise ValueError(
                    "Configure at least one remote host or use --docker/--multipass."
                )
            request = ProvisioningRequest(
                mode=ProvisioningMode.REMOTE,
                count=len(cfg.remote_hosts),
                remote_hosts=cfg.remote_hosts,
            )
        elif execution_mode is ProvisioningMode.DOCKER:
            request = ProvisioningRequest(
                mode=ProvisioningMode.DOCKER,
                count=node_count,
                docker_engine=docker_engine,
            )
        else:
            temp_dir = cfg.output_dir.parent / "temp_keys"
            request = ProvisioningRequest(
                mode=ProvisioningMode.MULTIPASS,
                count=node_count,
                state_dir=temp_dir,
            )
        provisioning_result = provisioner.provision(request)
    except ProvisioningError as exc:
        ui.present.error(f"Provisioning failed: {exc}")
        raise typer.Exit(1)
    except ValueError as exc:
        ui.present.error(str(exc))
        raise typer.Exit(1)

    cfg.remote_hosts = [node.host for node in provisioning_result.nodes]
    cfg.remote_execution.enabled = True

    result = None
    try:
        context = run_service.create_session(
            config_service=config_service,
            tests=tests,
            config_path=resolved,
            run_id=run_id,
            resume=resume,
            repetitions=repetitions,
            debug=debug,
            intensity=intensity,
            ui_adapter=ui_adapter,
            setup=setup,
            stop_file=stop_file,
            execution_mode=execution_mode.value,
            preloaded_config=cfg,
        )

        _print_run_plan(
            context.config,
            context.target_tests,
            registry=context.registry,
            execution_mode=execution_mode.value,
        )

        result = run_service.execute(context, run_id, ui_adapter=ui_adapter)

    except ValueError as e:
        ui.present.warning(str(e))
        raise typer.Exit(1)
    except Exception as exc:
        ui.present.error(f"Run failed: {exc}")
        raise typer.Exit(1)
    finally:
        _cleanup_provisioned_nodes(provisioning_result, result, ui.present)

    if result and result.journal_path and os.getenv("LB_SUPPRESS_SUMMARY", "").lower() not in ("1", "true", "yes"):
        _print_run_journal_summary(result.journal_path, log_path=result.log_path, ui_log_path=result.ui_log_path)

    ui.present.success("Run completed.")



def _select_plugins_interactively(
    registry: PluginRegistry, enabled_map: Dict[str, bool]
) -> Optional[Set[str]]:
    """Prompt the user to enable/disable plugins using arrows and space."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        ui.present.error("Interactive selection requires a TTY.")
        return None
        
    headers, rows = build_plugin_table(registry, enabled=enabled_map)
    ui.tables.show(TableModel(title="Available Workload Plugins", columns=headers, rows=rows))
    
    items = []
    for name, plugin in registry.available().items():
        desc = getattr(plugin, "description", "") or ""
        items.append(PickItem(id=name, title=name, description=desc))
    
    selection = ui.picker.pick_many(items, title="Select Workload Plugins")
    
    if not selection:
        ui.present.warning("Selection cancelled.")
        return None
        
    return {s.id for s in selection}


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
        ui.present.warning(f"Saved default config not found: {stale}")
    ui.present.success(f"Plugin selection saved to {target}")
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
    # Using echo here for non-UI/header output or remove?
    # ui.present.info? 
    # Just skip, show table.
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

    cfg_for_table: Optional[BenchmarkConfig] = None
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
        selection = _select_plugins_interactively(registry, enabled_map)
        if selection is None:
            raise typer.Exit(1)
        enabled_map = _apply_plugin_selection(registry, selection, config, set_default)

    headers, rows = build_plugin_table(registry, enabled=enabled_map)
    ui.tables.show(TableModel(title="Available Workload Plugins", columns=headers, rows=rows))


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
        help="Remember the config after enabling/disabling."
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
        ui.present.success(f"Plugin installed: {name}")
        ui.present.info("Run `lb plugin list` to verify.")
    except Exception as e:
        ui.present.error(f"Installation failed: {e}")
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
    requested_name = name
    if name.startswith(("http://", "https://", "git@")) or name.endswith(".git"):
         ui.present.warning(f"'{name}' looks like a URL/path. `uninstall` expects the plugin name (e.g. 'unixbench').")
         ui.present.info("Run `lb plugin list` to see installed plugins.")
         raise typer.Exit(1)

    installer = PluginInstaller()
    
    registry = create_registry()
    if name in registry.available():
        try:
            plugin = registry.get(name)
            plugin_file = Path(inspect.getfile(plugin.__class__)).resolve()
            plugin_root = installer.plugin_dir.resolve()
            if plugin_root in plugin_file.parents:
                rel_path = plugin_file.relative_to(plugin_root)
                dir_name = rel_path.parts[0]
                if dir_name != name:
                    name = dir_name
        except Exception:
            pass

    config_path: Optional[Path] = None
    config_stale: Optional[Path] = None
    removed_config = False
    try:
        removal_target = name
        removed_files = installer.uninstall(removal_target)

        if purge_config:
            try:
                _, config_path, config_stale, removed_config = config_service.remove_plugin(requested_name, config)
            except FileNotFoundError:
                if config is not None:
                    ui.present.warning(f"Config file not found: {config}")
            except Exception as exc:
                ui.present.warning(f"Config cleanup failed: {exc}")

        if removed_files:
            ui.present.success(f"Plugin '{name}' uninstalled.")
        else:
            ui.present.warning(f"Plugin '{name}' not found or not a user plugin.")

        if removed_config and config_path:
            ui.present.info(f"Removed '{requested_name}' from config {config_path}")
        if config_stale:
            ui.present.warning(f"Saved default config not found: {config_stale}")

    except Exception as e:
        ui.present.error(f"Uninstall failed: {e}")
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


def main() -> None:
    """Console script entrypoint (Typer app)."""
    app()


if __name__ == "__main__":
    main()
