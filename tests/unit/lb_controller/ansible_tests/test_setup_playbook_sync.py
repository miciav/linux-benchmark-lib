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
    archive_task = next(
        (
            task
            for task in tasks
            if task.get("name") == "Build benchmark library archive locally"
        ),
        None,
    )
    assert archive_task is not None
    cmd = None
    for key, value in archive_task.items():
        if key.endswith(".command") or key == "command":
            if isinstance(value, dict):
                cmd = value.get("cmd")
                break
    assert cmd is not None
    cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
    assert "lb_common" in cmd_str
