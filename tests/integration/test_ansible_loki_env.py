import yaml
from pathlib import Path
import pytest


def test_ansible_task_passes_loki_env():
    """Verify that run_single_rep.yml passes Loki env vars to the runner."""
    playbook_path = Path(
        "lb_controller/ansible/roles/workload_runner/tasks/run_single_rep.yml"
    )

    if not playbook_path.exists():
        pytest.fail(f"Playbook not found at {playbook_path}")

    content = yaml.safe_load(playbook_path.read_text())

    # Find the task that runs async_localrunner
    runner_task = None

    # The tasks are in a block? No, run_single_rep.yml is a list of tasks.
    # But wait, "Run workload repetition via LocalRunner" is a block.

    for item in content:
        if (
            "block" in item
            and item.get("name") == "Run workload repetition via LocalRunner"
        ):
            for subtask in item["block"]:
                # Identify by the command usage
                if "lb_runner.services.async_localrunner" in str(
                    subtask.get("ansible.builtin.command", "")
                ):
                    runner_task = subtask
                    break

    assert runner_task is not None, "Could not find async_localrunner task in playbook"

    env = runner_task.get("environment", {})

    assert "LB_LOKI_ENABLED" in env
    assert "LB_LOKI_ENDPOINT" in env

    # Check the Jinja2 templates are correct
    assert "workload_runner_config.loki.enabled" in env["LB_LOKI_ENABLED"]
    assert "workload_runner_config.loki.endpoint" in env["LB_LOKI_ENDPOINT"]
