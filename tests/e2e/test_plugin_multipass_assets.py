"""Ansible playbook checks for plugin Multipass assets."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pytest

from lb_plugins.api import PluginRegistry, builtin_plugins

MULTIPASS_ENV_FLAG = "MULTIPASS_TESTS"


@dataclass
class MultipassStatus:
    ready: bool
    reason: str


def _multipass_status() -> MultipassStatus:
    if shutil.which("ansible-playbook") is None:
        return MultipassStatus(False, "ansible-playbook not available")
    if shutil.which("multipass") is None:
        return MultipassStatus(False, "multipass CLI not found")
    info = subprocess.run(
        ["multipass", "version"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if info.returncode != 0:
        return MultipassStatus(
            False, f"multipass unavailable: {info.stderr or info.stdout}"
        )
    os.environ.setdefault(MULTIPASS_ENV_FLAG, "1")
    return MultipassStatus(True, "")


def _collect_playbooks() -> list[tuple[str, str, Path]]:
    """Collect plugins (builtin + user) that expose ansible setup/teardown playbooks."""
    registry = PluginRegistry(builtin_plugins())
    items: list[tuple[str, str, Path]] = []
    for plugin in registry.available(load_entrypoints=True).values():
        for kind, path in _iter_paths(plugin):
            if path and path.exists():
                items.append((plugin.name, kind, path))
    return items


def _iter_paths(plugin: object) -> Iterable[tuple[str, Path | None]]:
    yield "setup", getattr(plugin, "get_ansible_setup_path")()
    yield "teardown", getattr(plugin, "get_ansible_teardown_path")()


PLAYBOOKS = _collect_playbooks()

if not PLAYBOOKS:
    pytest.skip("No plugin Ansible playbooks found", allow_module_level=True)

MULTIPASS_READY = _multipass_status()

pytestmark = [pytest.mark.inter_e2e, pytest.mark.inter_multipass, pytest.mark.slow]


@pytest.mark.skipif(
    not MULTIPASS_READY.ready, reason=MULTIPASS_READY.reason or "multipass unavailable"
)
@pytest.mark.parametrize("plugin_name,kind,playbook_path", PLAYBOOKS)
def test_plugin_playbook_syntax(
    plugin_name: str, kind: str, playbook_path: Path
) -> None:
    """Run ansible syntax-check on each plugin playbook."""
    result = subprocess.run(
        ["ansible-playbook", "--syntax-check", str(playbook_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(
            f"Playbook syntax-check failed for {plugin_name} ({kind})\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
