"""Unit tests for the remote benchmark controller."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from linux_benchmark_lib.benchmark_config import BenchmarkConfig, RemoteHostConfig
from linux_benchmark_lib.controller import (
    AnsibleRunnerExecutor,
    BenchmarkController,
    ExecutionResult,
    InventorySpec,
    RemoteExecutor,
)


class DummyExecutor(RemoteExecutor):
    """Executor stub that records playbook invocations."""

    def __init__(self) -> None:
        self.calls = []

    def run_playbook(
        self,
        playbook_path: Path,
        inventory: InventorySpec,
        extravars=None,
        tags=None,
    ) -> ExecutionResult:
        self.calls.append(
            {
                "playbook": playbook_path,
                "inventory": inventory,
                "extravars": extravars or {},
                "tags": tags or [],
            }
        )
        return ExecutionResult(rc=0, status="successful")


def test_controller_creates_output_dirs(tmp_path: Path):
    """Controller should prepare per-run and per-host directories."""
    config = BenchmarkConfig(
        output_dir=tmp_path / "out",
        report_dir=tmp_path / "rep",
        data_export_dir=tmp_path / "exp",
        remote_hosts=[RemoteHostConfig(name="node1", address="127.0.0.1")],
    )
    executor = DummyExecutor()
    controller = BenchmarkController(config, executor=executor)

    summary = controller.run(test_types=["stress_ng"], run_id="run-test")

    host_dir = config.output_dir / "run-test" / "node1"
    report_dir = config.report_dir / "run-test" / "node1"

    assert summary.success
    assert host_dir.exists()
    assert report_dir.exists()
    # setup + run + collect phases
    assert len(executor.calls) == 3


def test_top500_runs_via_workload_runner(tmp_path: Path):
    """Top500 workload should flow through the workload runner like other plugins."""
    config = BenchmarkConfig(
        output_dir=tmp_path / "out",
        report_dir=tmp_path / "rep",
        data_export_dir=tmp_path / "exp",
        remote_hosts=[RemoteHostConfig(name="node1", address="127.0.0.1")],
    )
    executor = DummyExecutor()
    controller = BenchmarkController(config, executor=executor)

    summary = controller.run(test_types=["top500"], run_id="run-top500")

    assert summary.success
    assert len(executor.calls) == 3
    assert all("top500" in call["extravars"]["tests"] for call in executor.calls)
    assert all("top500.yml" not in str(call["playbook"]) for call in executor.calls)


def test_ansible_runner_renders_inventory(tmp_path: Path):
    """AnsibleRunnerExecutor should write inventory and pass parameters to runner."""
    called_kwargs = {}

    def fake_runner(**kwargs):
        called_kwargs.update(kwargs)
        return SimpleNamespace(rc=0, status="ok", stats={"ok": 1})

    executor = AnsibleRunnerExecutor(
        private_data_dir=tmp_path / "ansible",
        runner_fn=fake_runner,
    )

    playbook = tmp_path / "play.yml"
    playbook.write_text("- hosts: all\n  tasks: []\n")

    hosts = [
        RemoteHostConfig(
            name="node1",
            address="10.0.0.1",
            user="ubuntu",
            vars={"role": "db"},
        )
    ]
    inventory = InventorySpec(hosts=hosts)

    result = executor.run_playbook(
        playbook_path=playbook,
        inventory=inventory,
        extravars={"foo": "bar"},
        tags=["smoke"],
    )

    inventory_path = Path(called_kwargs["inventory"])
    content = inventory_path.read_text()

    assert "node1 ansible_host=10.0.0.1" in content
    assert "ansible_user=ubuntu" in content
    assert "role=db" in content
    assert called_kwargs["tags"] == "smoke"
    assert called_kwargs["extravars"]["foo"] == "bar"
    assert result.success
