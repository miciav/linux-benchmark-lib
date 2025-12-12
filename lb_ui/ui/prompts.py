"""Interactive prompt helpers."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Sequence, Set, Tuple, TypeVar, Callable

from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table

from lb_controller.ui_interfaces import UIAdapter
from lb_controller.services.run_catalog_service import RunInfo

console = Console()

_T = TypeVar("_T")


def _check_tty() -> bool:
    """Return True when running in an interactive terminal."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def _load_inquirer() -> Optional[Any]:
    """Return the InquirerPy module when available."""
    try:
        from InquirerPy import inquirer
    except Exception:
        return None
    return inquirer


def prompt_plugins(
    plugins: Dict[str, str],
    enabled: Dict[str, bool],
    force: bool = False,
    show_table: bool = True,
) -> Optional[Set[str]]:
    """
    Prompt for plugin selection using a checkbox selector; fall back to text input.

    Returns a set of enabled plugin names, or None if cancelled/non-interactive.
    """
    if not (_check_tty() or force):
        return None

    inquirer = _load_inquirer()
    if inquirer is None:
        console.print(
            "[yellow]InquirerPy not installed; keeping existing plugin selection.[/yellow]"
        )
        return {name for name, active in enabled.items() if active}

    if show_table:
        table = Table(title="Workload plugins", show_lines=False)
        table.add_column("Enabled")
        table.add_column("Plugin")
        table.add_column("Description")
        for name, description in sorted(plugins.items()):
            marker = "[green]✓[/green]" if enabled.get(name, False) else "[dim]·[/dim]"
            table.add_row(marker, name, description or "-")

        console.print(table)

    choices = []
    for name, description in sorted(plugins.items()):
        label = f"{name} — {description}" if description else name
        choices.append(
            {"name": label, "value": name, "enabled": enabled.get(name, False)}
        )
    result = inquirer.checkbox(
        message="Select workload plugins",
        choices=choices,
        instruction="Space to toggle, Enter to confirm",
        transformer=lambda values: ", ".join(values),
        cycle=True,
    ).execute()
    return set(result) if result is not None else None


@dataclass
class RemoteHostDetails:
    """Collected remote host fields from the wizard."""

    name: str
    address: str
    user: str
    key_path: str
    become: bool


def prompt_remote_host(defaults: Optional[Dict[str, str]] = None) -> Optional[RemoteHostDetails]:
    """Collect a single remote host definition via prompts."""
    if not _check_tty():
        return None
    defaults = defaults or {}
    console.print("[bold]Configure remote host[/bold]")
    name = Prompt.ask("Host name", default=defaults.get("name", "node1")).strip()
    address = Prompt.ask("Host address", default=defaults.get("address", "192.168.1.10")).strip()
    user = Prompt.ask("SSH user", default=defaults.get("user", "ubuntu")).strip()
    key_path = Prompt.ask("SSH private key path", default=defaults.get("key_path", "~/.ssh/id_rsa")).strip()
    become = Confirm.ask("Use sudo (become)?", default=True)
    return RemoteHostDetails(name=name, address=address, user=user, key_path=key_path, become=bool(become))


def prompt_multipass(
    options: Iterable[str],
    ui_adapter: UIAdapter,
    default_level: str = "medium",
) -> Optional[Tuple[str, str]]:
    """Prompt for Multipass scenario and intensity."""
    if not _check_tty():
        return None

    options_list = list(options)
    descriptions = {
        "stress_ng": "CPU/memory stress (default)",
        "dd": "Disk throughput (dd)",
        "fio": "Random I/O (fio)",
        "multi": "stress_ng + dd + fio combo",
    }

    rows = [[name, descriptions.get(name, "-")] for name in options_list]
    ui_adapter.show_table("Multipass Scenarios", ["Scenario", "Description"], rows)

    inquirer = _load_inquirer()
    if inquirer is None:
        fallback = options_list[0] if options_list else "stress_ng"
        ui_adapter.show_warning(
            f"InquirerPy not installed; selecting {fallback} @ {default_level}."
        )
        return fallback, default_level

    choices = [
        {"name": f"{name} — {descriptions.get(name, '')}".strip(" —"), "value": name}
        for name in options_list
    ]
    selection = inquirer.checkbox(
        message="Select one Multipass scenario",
        choices=choices,
        default=[options_list[0]] if options_list else None,
        instruction="Space to toggle, Enter to confirm",
        validate=lambda result: len(result) == 1 or "Select exactly one scenario",
    ).execute()
    if not selection:
        return None
    scenario = selection[0]
    level = inquirer.select(
        message="Select intensity",
        choices=["low", "medium", "high"],
        default=default_level,
    ).execute()
    return scenario, level


def prompt_run_id(runs: Sequence[RunInfo], ui_adapter: UIAdapter) -> Optional[str]:
    """Prompt the user to select a run_id from available runs."""
    if not _check_tty():
        return None
    if not runs:
        return None

    rows = []
    for run in runs:
        created = run.created_at.isoformat() if run.created_at else "-"
        rows.append([run.run_id, created, ", ".join(run.workloads) or "-"])
    ui_adapter.show_table("Available Runs", ["Run ID", "Created", "Workloads"], rows)

    inquirer = _load_inquirer()
    if inquirer is None:
        return runs[0].run_id

    choices = [
        {
            "name": f"{run.run_id} — {run.created_at.isoformat() if run.created_at else ''}".strip(
                " —"
            ),
            "value": run.run_id,
        }
        for run in runs
    ]
    selection = inquirer.select(
        message="Select a benchmark run",
        choices=choices,
        default=runs[0].run_id,
        cycle=True,
    ).execute()
    return str(selection) if selection else None


def prompt_analytics_kind(
    kinds: Sequence[str], ui_adapter: UIAdapter, default: str = "aggregate"
) -> Optional[str]:
    """Prompt the user to select an analytics kind."""
    if not _check_tty():
        return None
    if not kinds:
        return None
    rows = [[kind, "-"] for kind in kinds]
    ui_adapter.show_table("Analytics Types", ["Kind", "Description"], rows)

    inquirer = _load_inquirer()
    if inquirer is None:
        return default if default in kinds else kinds[0]
    selection = inquirer.select(
        message="Select analytics type",
        choices=[{"name": k, "value": k} for k in kinds],
        default=default if default in kinds else kinds[0],
        cycle=True,
    ).execute()
    return str(selection) if selection else None


def prompt_multi_select(
    label: str,
    options: Sequence[_T],
    render: Optional[Callable[[_T], str]] = None,
    default_all: bool = True,
) -> Optional[Set[_T]]:
    """Prompt for multi-selection of values; returns None when cancelled."""
    if not _check_tty():
        return None
    if not options:
        return set()
    inquirer = _load_inquirer()
    if inquirer is None:
        return set(options) if default_all else set()
    choices = []
    for opt in options:
        name = render(opt) if render else str(opt)
        choices.append({"name": name, "value": opt, "enabled": default_all})
    result = inquirer.checkbox(
        message=label,
        choices=choices,
        instruction="Space to toggle, Enter to confirm",
        cycle=True,
    ).execute()
    return set(result) if result is not None else None
