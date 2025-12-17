"""Unit tests for the remote benchmark controller."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from lb_runner.benchmark_config import BenchmarkConfig, RemoteHostConfig, WorkloadConfig

pytestmark = pytest.mark.unit

from lb_controller.controller import (
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
        limit_hosts=None,
    ) -> ExecutionResult:
        self.calls.append(
            {
                "playbook": playbook_path,
                "inventory": inventory,
                "extravars": extravars or {},
                "tags": tags or [],
                "limit_hosts": limit_hosts or [],
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
    config.workloads = {"stress_ng": WorkloadConfig(plugin="stress_ng")}
    config.repetitions = 1
    config.remote_execution.run_teardown = False
    executor = DummyExecutor()
    controller = BenchmarkController(config, executor=executor)

    summary = controller.run(test_types=["stress_ng"], run_id="run-test")

    host_dir = config.output_dir / "run-test" / "node1"
    report_dir = config.report_dir / "run-test" / "node1"

    assert summary.success
    assert host_dir.exists()
    assert report_dir.exists()
    run_calls = [
        call for call in executor.calls if "run_benchmark" in str(call["playbook"])
    ]
    assert run_calls, "Expected run playbook to be invoked"
    assert run_calls[0]["extravars"].get("repetition_index") == 0
    per_host_output = run_calls[0]["extravars"].get("per_host_output")
    assert per_host_output is not None, "per_host_output extravar should be set"
    assert per_host_output.get("node1") == str(host_dir)


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


def test_controller_merges_plugin_extravars_into_setup(tmp_path: Path) -> None:
    """Controller should merge plugin-provided extravars into setup/teardown runs."""
    config = BenchmarkConfig(
        output_dir=tmp_path / "out",
        report_dir=tmp_path / "rep",
        data_export_dir=tmp_path / "exp",
        remote_hosts=[RemoteHostConfig(name="node1", address="127.0.0.1")],
    )
    config.workloads = {
        "pts_build_linux_kernel": WorkloadConfig(plugin="pts_build_linux_kernel")
    }
    config.repetitions = 1
    config.remote_execution.run_setup = False
    config.remote_execution.run_collect = False
    config.remote_execution.run_teardown = False

    executor = DummyExecutor()
    controller = BenchmarkController(config, executor=executor)
    summary = controller.run(test_types=["pts_build_linux_kernel"], run_id="run-test")
    assert summary.success

    setup_calls = [
        call for call in executor.calls if str(call["playbook"]).endswith("/phoronix_test_suite/ansible/setup.yml")
    ]
    assert setup_calls, "Expected PTS setup playbook call"
    assert setup_calls[0]["extravars"]["pts_profile"] == "build-linux-kernel"
    assert "pts_deb_relpath" in setup_calls[0]["extravars"]
    assert "pts_home_root" in setup_calls[0]["extravars"]

    teardown_calls = [
        call
        for call in executor.calls
        if str(call["playbook"]).endswith("/phoronix_test_suite/ansible/teardown.yml")
    ]
    assert teardown_calls, "Expected PTS teardown playbook call"
    assert teardown_calls[0]["extravars"]["pts_profile"] == "build-linux-kernel"
