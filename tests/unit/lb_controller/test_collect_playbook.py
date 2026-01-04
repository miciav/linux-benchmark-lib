from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit_controller]


def _load_playbook(relative_path: str) -> list[dict]:
    repo_root = Path(__file__).resolve().parents[3]
    path = repo_root / "lb_controller" / "ansible" / relative_path
    data = yaml.safe_load(path.read_text())
    assert isinstance(data, list)
    assert data
    tasks = data[0].get("tasks", [])
    assert isinstance(tasks, list)
    return tasks


def _has_find_jsonl_task(tasks: list[dict]) -> bool:
    for task in tasks:
        find_cfg = task.get("ansible.builtin.find", {})
        if not isinstance(find_cfg, dict):
            continue
        patterns = find_cfg.get("patterns")
        if patterns == "*.jsonl":
            return True
    return False


def _has_fetch_logs_task(tasks: list[dict]) -> bool:
    for task in tasks:
        fetch_cfg = task.get("ansible.builtin.fetch", {})
        if not isinstance(fetch_cfg, dict):
            continue
        dest = fetch_cfg.get("dest", "")
        if isinstance(dest, str) and "/logs" in dest:
            return True
    return False


def _has_logs_dir_task(tasks: list[dict]) -> bool:
    for task in tasks:
        file_cfg = task.get("ansible.builtin.file", {})
        if not isinstance(file_cfg, dict):
            continue
        path = file_cfg.get("path", "")
        if isinstance(path, str) and path.endswith("/logs"):
            return True
    return False


def test_collect_playbook_has_log_collection_tasks() -> None:
    tasks = _load_playbook("playbooks/collect.yml")
    assert _has_find_jsonl_task(tasks)
    assert _has_fetch_logs_task(tasks)
    assert _has_logs_dir_task(tasks)
