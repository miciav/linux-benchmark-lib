"""Characterization tests for SetupService."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from lb_controller.api import ExecutionResult
from lb_controller.services import setup_service as setup_service_module
from lb_controller.services.setup_service import SetupService
from lb_plugins.api import PluginAssetConfig
from lb_runner.api import DEFAULT_LB_WORKDIR

pytestmark = pytest.mark.unit_controller


class DummyExecutor:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run_playbook(
        self,
        playbook_path: Path,
        inventory,
        extravars=None,
        tags=None,
        limit_hosts=None,
        *,
        cancellable: bool = True,
    ) -> ExecutionResult:
        self.calls.append(
            {
                "playbook": playbook_path,
                "inventory": inventory,
                "extravars": extravars,
                "cancellable": cancellable,
            }
        )
        return ExecutionResult(rc=0, status="successful")


def test_provision_global_uses_local_inventory(tmp_path: Path, monkeypatch) -> None:
    ansible_root = tmp_path / "ansible"
    playbooks = ansible_root / "playbooks"
    playbooks.mkdir(parents=True)
    setup_path = playbooks / "setup.yml"
    setup_path.write_text("---\n- hosts: all\n  tasks: []\n")
    monkeypatch.setattr(setup_service_module, "ANSIBLE_ROOT", ansible_root)

    executor = DummyExecutor()
    service = SetupService(executor=executor)

    assert service.provision_global() is True

    assert executor.calls
    call = executor.calls[0]
    inventory = call["inventory"]
    host = inventory.hosts[0]
    assert host.name == "localhost"
    assert host.vars["ansible_connection"] == "local"
    assert host.vars["ansible_python_interpreter"] == sys.executable
    assert call["extravars"] == {"lb_workdir": DEFAULT_LB_WORKDIR}


def test_provision_workload_skips_when_missing_playbook(tmp_path: Path) -> None:
    executor = DummyExecutor()
    service = SetupService(executor=executor)

    assert service.provision_workload(None, "dummy") is True
    assert executor.calls == []


def test_teardown_workload_marks_uncancellable(tmp_path: Path, monkeypatch) -> None:
    ansible_root = tmp_path / "ansible"
    playbooks = ansible_root / "playbooks"
    playbooks.mkdir(parents=True)
    teardown_path = playbooks / "teardown.yml"
    teardown_path.write_text("---\n- hosts: all\n  tasks: []\n")
    monkeypatch.setattr(setup_service_module, "ANSIBLE_ROOT", ansible_root)

    executor = DummyExecutor()
    service = SetupService(executor=executor)

    assets = PluginAssetConfig(
        setup_playbook=None,
        teardown_playbook=teardown_path,
        setup_extravars={},
        teardown_extravars={"foo": "bar"},
    )

    assert service.teardown_workload(assets, "dummy") is True
    call = executor.calls[0]
    assert call["playbook"] == teardown_path
    assert call["extravars"] == {"foo": "bar"}
    assert call["cancellable"] is False
