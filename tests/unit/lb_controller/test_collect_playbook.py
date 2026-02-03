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
    tasks: list[dict] = []
    for play in data:
        play_tasks = play.get("tasks", [])
        play_pre_tasks = play.get("pre_tasks", [])
        if isinstance(play_pre_tasks, list):
            tasks.extend(play_pre_tasks)
        if isinstance(play_tasks, list):
            tasks.extend(play_tasks)
    assert tasks
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


def _has_stream_log_fetch_task(tasks: list[dict]) -> bool:
    for task in tasks:
        fetch_cfg = task.get("ansible.builtin.fetch", {})
        if not isinstance(fetch_cfg, dict):
            continue
        src = fetch_cfg.get("src", "")
        dest = fetch_cfg.get("dest", "")
        if isinstance(src, str) and "lb_events.stream.log" in src:
            if isinstance(dest, str) and "lb_events-" in dest:
                return True
    return False


def _has_plugin_derive_task(tasks: list[dict]) -> bool:
    for task in tasks:
        inc = task.get("include_tasks")
        if isinstance(inc, str) and "collect_pre_playbook" in inc:
            return True
    return False


def _has_k6_log_collection(tasks: list[dict]) -> bool:
    found = False
    for task in tasks:
        find_cfg = task.get("ansible.builtin.find", {})
        if isinstance(find_cfg, dict) and find_cfg.get("patterns") == "k6.log":
            found = True
            continue
        fetch_cfg = task.get("ansible.builtin.fetch", {})
        if isinstance(fetch_cfg, dict):
            dest = fetch_cfg.get("dest", "")
            if isinstance(dest, str) and "/logs/k6/" in dest:
                found = True
    return found


def test_collect_playbook_has_log_collection_tasks() -> None:
    tasks = _load_playbook("playbooks/collect.yml")
    assert _has_find_jsonl_task(tasks)
    assert _has_fetch_logs_task(tasks)
    assert _has_logs_dir_task(tasks)
    assert _has_stream_log_fetch_task(tasks)
    assert _has_plugin_derive_task(tasks)


def test_dfaas_plugin_collect_post_playbook() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    path = repo_root / "lb_plugins" / "plugins" / "peva_faas" / "ansible" / "collect" / "post.yml"
    data = yaml.safe_load(path.read_text())
    assert isinstance(data, list)
    if data and isinstance(data[0], dict) and "tasks" in data[0]:
        tasks = data[0].get("tasks", [])
    else:
        tasks = data
    assert _has_k6_log_collection(tasks)
