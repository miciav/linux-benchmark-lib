from pathlib import Path

import pytest
import yaml


pytestmark = [pytest.mark.unit_plugins]


@pytest.mark.parametrize(
    ("plugin_name", "alias"),
    [
        ("dfaas", "dfaas"),
        ("peva_faas", "peva_faas"),
    ],
)
def test_faas_collect_pre_registers_k6_host_only_when_remote(
    plugin_name: str, alias: str
) -> None:
    path = (
        Path(__file__).resolve().parents[3]
        / "lb_plugins"
        / "plugins"
        / plugin_name
        / "ansible"
        / "collect"
        / "pre.yml"
    )
    tasks = yaml.safe_load(path.read_text())
    assert isinstance(tasks, list) and tasks

    derive_task = next(
        (
            task
            for task in tasks
            if task.get("name") == "Derive DFaaS k6 settings from benchmark config"
        ),
        None,
    )
    assert derive_task is not None
    derive_text = str(derive_task.get("ansible.builtin.set_fact", {}))
    assert "127.0.0.1" in derive_text
    assert "localhost" in derive_text
    assert f"{alias}_k6_is_remote" in derive_text

    register_task = next(
        (
            task
            for task in tasks
            if task.get("name") == "Register DFaaS k6 host"
        ),
        None,
    )
    assert register_task is not None
    when_clause = register_task.get("when", [])
    if isinstance(when_clause, str):
        when_items = [when_clause]
    else:
        when_items = [str(item) for item in when_clause]
    when_text = " ".join(when_items)
    assert f"{alias}_k6_is_remote" in when_text
