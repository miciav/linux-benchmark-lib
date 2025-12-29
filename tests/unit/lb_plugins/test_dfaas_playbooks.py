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


def test_setup_k6_playbook_installs_k6() -> None:
    playbook = _load_playbook("setup_k6.yml")
    tasks = playbook[0]["tasks"]
    assert any(
        task.get("ansible.builtin.apt", {}).get("name") == "k6"
        for task in tasks
    )


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
