"""
Rich-based interactive helpers used by the CLI.

These helpers avoid Textual entirely while still offering a small amount of
structured input when a TTY is available.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Set, Tuple

from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table


console = Console()


def _check_tty() -> bool:
    """Return True when running in an interactive terminal."""
    return sys.stdin.isatty() and sys.stdout.isatty()


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

    from InquirerPy import inquirer

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


def prompt_multipass(options: Iterable[str], default_level: str = "medium") -> Optional[Tuple[str, str]]:
    """Prompt for Multipass scenario and intensity."""
    if not _check_tty():
        return None

    options_list = list(options)
    descriptions = {
        "stress_ng": "CPU/memory stress (default)",
        "dd": "Disk throughput (dd)",
        "fio": "Random I/O (fio)",
        "iperf3": "Network throughput",
        "multi": "stress_ng + dd + fio combo",
        "top500": "Top500 setup only",
    }

    table = Table(title="Multipass scenarios", show_lines=False)
    table.add_column("Scenario")
    table.add_column("Description")
    for name in options_list:
        table.add_row(name, descriptions.get(name, "-"))
    console.print(table)

    from InquirerPy import inquirer

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
