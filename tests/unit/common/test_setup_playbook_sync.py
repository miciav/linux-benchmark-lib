"""Tests for controller setup playbook content."""

from pathlib import Path

import pytest
import yaml


pytestmark = pytest.mark.unit_controller


def test_setup_playbook_sync_includes_lb_common() -> None:
    """Ensure setup.yml syncs lb_common to remote hosts."""
    playbook = Path("lb_controller/ansible/playbooks/setup.yml")
    data = yaml.safe_load(playbook.read_text())
    assert isinstance(data, list) and data
    tasks = data[0].get("tasks", [])
    copy_task = next(
        (
            task
            for task in tasks
            if task.get("name")
            == "Synchronize benchmark library sources to remote host"
        ),
        None,
    )
    assert copy_task is not None
    loop = copy_task.get("loop") or []
    assert "lb_common" in loop
    assert "lb_ui" not in loop
