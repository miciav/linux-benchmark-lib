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
    plugins: Dict[str, str], enabled: Dict[str, bool], force: bool = False
) -> Optional[Set[str]]:
    """
    Prompt for plugin selection using a simple rich table + comma-separated input.

    Returns a set of enabled plugin names, or None if cancelled/non-interactive.
    """
    if not (_check_tty() or force):
        return None

    table = Table(title="Workload plugins", show_lines=False)
    table.add_column("Enabled")
    table.add_column("Plugin")
    table.add_column("Description")
    for name, description in sorted(plugins.items()):
        marker = "[green]✓[/green]" if enabled.get(name, False) else "[dim]·[/dim]"
        table.add_row(marker, name, description or "-")

    console.print(table)
    current = ",".join(sorted(name for name, state in enabled.items() if state))
    raw = Prompt.ask(
        "Enable plugins (comma separated, blank to keep current, 'all' for every plugin)",
        default=current,
    ).strip()
    if raw.lower() in ("", "cancel"):
        return None
    if raw.lower() == "all":
        return set(plugins.keys())
    selected = {item.strip() for item in raw.split(",") if item.strip()}
    return selected


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
    console.print("[bold]Select Multipass scenario[/bold]")
    for name in options:
        console.print(f"- {name}")
    scenario = Prompt.ask("Scenario", default=next(iter(options), "stress_ng"))
    level = Prompt.ask("Intensity (low/medium/high)", choices=["low", "medium", "high"], default=default_level)
    return scenario, level
