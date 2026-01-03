from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit_plugins]


def _load_playbook(name: str) -> list[dict]:
    repo_root = Path(__file__).resolve().parents[3]
    path = repo_root / "lb_plugins" / "plugins" / "dfaas" / "ansible" / name
    data = yaml.safe_load(path.read_text())
    assert isinstance(data, list)
    assert data
    return data


def _find_apt_tasks(tasks: list[dict], name: str) -> bool:
    """Recursively find apt tasks with given package name, including inside blocks."""
    for task in tasks:
        # Check direct apt task
        apt_config = task.get("ansible.builtin.apt", {})
        if apt_config.get("name") == name:
            return True
        # Check if name is in a list of packages
        if isinstance(apt_config.get("name"), list) and name in apt_config.get("name"):
            return True
        # Check inside block structures
        if "block" in task:
            if _find_apt_tasks(task["block"], name):
                return True
        # Check inside rescue structures
        if "rescue" in task:
            if _find_apt_tasks(task["rescue"], name):
                return True
    return False


def test_setup_k6_playbook_installs_k6() -> None:
    playbook = _load_playbook("setup_k6.yml")
    tasks = playbook[0]["tasks"]
    # k6 is installed via apt inside a block/rescue structure
    assert _find_apt_tasks(tasks, "k6"), "k6 apt installation not found in playbook"


def test_run_k6_playbook_runs_k6_with_summary() -> None:
    playbook = _load_playbook("run_k6.yml")
    tasks = playbook[0]["tasks"]
    shell_cmds = [
        task.get("ansible.builtin.shell") or task.get("shell") or ""
        for task in tasks
    ]
    assert any("k6 run" in cmd for cmd in shell_cmds)
    assert any("--summary-export" in cmd for cmd in shell_cmds)


def test_teardown_k6_playbook_has_cleanup() -> None:
    playbook = _load_playbook("teardown_k6.yml")
    tasks = playbook[0]["tasks"]
    assert any(
        task.get("ansible.builtin.file", {}).get("state") == "absent"
        for task in tasks
    )


def test_setup_target_playbook_has_core_steps() -> None:
    playbook = _load_playbook("setup_target.yml")
    tasks = playbook[0]["tasks"]
    commands = [
        task.get("ansible.builtin.command") or task.get("ansible.builtin.shell") or ""
        for task in tasks
    ]
    assert any("get.k3s.io" in cmd for cmd in commands)
    assert any("helm upgrade --install openfaas" in cmd for cmd in commands)
    assert any("kubectl apply -f" in cmd for cmd in commands)
