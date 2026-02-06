from pathlib import Path

import pytest
import yaml


def test_run_single_rep_cleans_stale_stop_file() -> None:
    """Ensure stale stop files from previous runs are removed before execution."""
    playbook_path = Path(
        "lb_controller/ansible/roles/workload_runner/tasks/run_single_rep.yml"
    )
    if not playbook_path.exists():
        pytest.fail(f"Playbook not found at {playbook_path}")

    content = yaml.safe_load(playbook_path.read_text())
    assert isinstance(content, list) and content

    runner_block = next(
        (
            item
            for item in content
            if item.get("name") == "Run workload repetition via LocalRunner"
            and isinstance(item.get("block"), list)
        ),
        None,
    )
    assert runner_block is not None, "Could not find LocalRunner execution block"

    cleanup_task = next(
        (
            task
            for task in runner_block["block"]
            if task.get("name") == "{{ run_prefix }} Clean up previous run artifacts"
        ),
        None,
    )
    assert cleanup_task is not None, "Could not find cleanup task in runner block"

    cleanup_loop = cleanup_task.get("loop", [])
    assert "{{ workload_runner_workdir }}/STOP" in cleanup_loop
