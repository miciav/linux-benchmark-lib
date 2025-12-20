"""Unit tests for the remote benchmark controller."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from lb_runner.benchmark_config import BenchmarkConfig, RemoteHostConfig, WorkloadConfig

pytestmark = pytest.mark.controller

from lb_controller.api import (
    AnsibleRunnerExecutor,
    BenchmarkController,
    ControllerState,
    ExecutionResult,
    InventorySpec,
    RemoteExecutor,
)
from lb_runner.stop_token import StopToken


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
        *,
        cancellable: bool = True,
    ) -> ExecutionResult:
        self.calls.append(
            {
                "playbook": playbook_path,
                "inventory": inventory,
                "extravars": extravars or {},
                "tags": tags or [],
                "limit_hosts": limit_hosts or [],
                "cancellable": cancellable,
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


def test_ansible_runner_short_circuits_when_stopped(tmp_path: Path):
    stop_token = StopToken(enable_signals=False)
    stop_token.request_stop()
    executor = AnsibleRunnerExecutor(
        private_data_dir=tmp_path / "ansible",
        stop_token=stop_token,
        runner_fn=lambda **_kwargs: SimpleNamespace(rc=0, status="ok", stats={}),
    )
    playbook = tmp_path / "play.yml"
    playbook.write_text("- hosts: all\n  tasks: []\n")
    inventory = InventorySpec(
        hosts=[RemoteHostConfig(name="node1", address="127.0.0.1", user="root")]
    )

    result = executor.run_playbook(playbook, inventory)
    assert result.status == "stopped"


def test_ansible_runner_interrupt_is_idempotent(tmp_path: Path):
    executor = AnsibleRunnerExecutor(
        private_data_dir=tmp_path / "ansible",
        runner_fn=lambda **_kwargs: SimpleNamespace(rc=0, status="ok", stats={}),
    )

    class DummyProc:
        def __init__(self) -> None:
            self.terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

    dummy = DummyProc()
    executor._active_process = dummy  # type: ignore[attr-defined]
    executor.interrupt()
    assert dummy.terminated
    assert executor.is_running is False


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
        call
        for call in executor.calls
        if str(call["playbook"]).endswith("/phoronix_test_suite/ansible/setup.yml")
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


def test_controller_runs_teardown_even_after_stop_requested(tmp_path: Path) -> None:
    """Stop requests should still allow plugin/global teardown to execute exactly once."""
    config = BenchmarkConfig(
        output_dir=tmp_path / "out",
        report_dir=tmp_path / "rep",
        data_export_dir=tmp_path / "exp",
        remote_hosts=[RemoteHostConfig(name="node1", address="127.0.0.1")],
    )
    config.workloads = {"stress_ng": WorkloadConfig(plugin="stress_ng")}
    config.repetitions = 1
    config.remote_execution.run_setup = False
    config.remote_execution.run_collect = False
    config.remote_execution.run_teardown = True

    stop_token = StopToken(enable_signals=False)
    run_playbook_path = config.remote_execution.run_playbook

    class StopAfterRunExecutor(RemoteExecutor):
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []
            self._stopped = False

        def run_playbook(
            self,
            playbook_path: Path,
            inventory: InventorySpec,
            extravars=None,
            tags=None,
            limit_hosts=None,
            *,
            cancellable: bool = True,
        ) -> ExecutionResult:
            self.calls.append(
                {
                    "playbook": playbook_path,
                    "cancellable": cancellable,
                }
            )
            if not self._stopped and playbook_path == run_playbook_path:
                self._stopped = True
                stop_token.request_stop()
                return ExecutionResult(rc=1, status="stopped")
            return ExecutionResult(rc=0, status="successful")

    executor = StopAfterRunExecutor()
    controller = BenchmarkController(
        config, executor=executor, stop_token=stop_token, stop_timeout_s=0.0
    )
    controller.run(test_types=["stress_ng"], run_id="run-test")

    td_calls = [c for c in executor.calls if "teardown" in str(c["playbook"])]
    assert td_calls, "Expected at least one teardown call"
    assert all(c["cancellable"] is False for c in td_calls)
    global_td_calls = [
        c
        for c in executor.calls
        if "/ansible/playbooks/teardown.yml" in str(c["playbook"])
    ]
    assert len(global_td_calls) == 1


def test_controller_interrupt_setup_triggers_teardown(tmp_path: Path) -> None:
    """When stop is requested during setup, controller should still run global teardown."""
    config = BenchmarkConfig(
        output_dir=tmp_path / "out",
        report_dir=tmp_path / "rep",
        data_export_dir=tmp_path / "exp",
        remote_hosts=[RemoteHostConfig(name="node1", address="127.0.0.1")],
    )
    config.workloads = {"stress_ng": WorkloadConfig(plugin="stress_ng")}
    config.repetitions = 1
    config.remote_execution.run_setup = True
    config.remote_execution.run_collect = False
    config.remote_execution.run_teardown = True

    stop_token = StopToken(enable_signals=False)

    setup_pb = config.remote_execution.setup_playbook
    teardown_pb = config.remote_execution.teardown_playbook

    class InterruptSetupExecutor(RemoteExecutor):
        def __init__(self) -> None:
            self.calls = []

        def run_playbook(
            self,
            playbook_path: Path,
            inventory: InventorySpec,
            extravars=None,
            tags=None,
            limit_hosts=None,
            *,
            cancellable: bool = True,
        ) -> ExecutionResult:
            self.calls.append({"playbook": playbook_path, "cancellable": cancellable})
            if playbook_path == setup_pb:
                stop_token.request_stop()
                return ExecutionResult(rc=1, status="stopped")
            return ExecutionResult(rc=0, status="successful")

    executor = InterruptSetupExecutor()
    controller = BenchmarkController(
        config, executor=executor, stop_token=stop_token, stop_timeout_s=0.0
    )
    summary = controller.run(test_types=["stress_ng"], run_id="run-test")
    assert summary.success is False
    teardown_calls = [c for c in executor.calls if c["playbook"] == teardown_pb]
    assert teardown_calls, "Expected global teardown to run after setup interruption"


def test_controller_sets_aborted_state_on_setup_stop(tmp_path: Path) -> None:
    """Stop during setup should mark controller aborted and allow cleanup."""
    config = BenchmarkConfig(
        output_dir=tmp_path / "out",
        report_dir=tmp_path / "rep",
        data_export_dir=tmp_path / "exp",
        remote_hosts=[RemoteHostConfig(name="node1", address="127.0.0.1")],
    )
    config.workloads = {"stress_ng": WorkloadConfig(plugin="stress_ng")}
    config.repetitions = 1
    config.remote_execution.run_teardown = False

    stop_token = StopToken(enable_signals=False)

    class StopDuringSetupExecutor(DummyExecutor):
        def run_playbook(
            self,
            playbook_path: Path,
            inventory: InventorySpec,
            extravars=None,
            tags=None,
            limit_hosts=None,
            *,
            cancellable: bool = True,
        ) -> ExecutionResult:
            stop_token.request_stop()
            return ExecutionResult(rc=1, status="stopped")

    executor = StopDuringSetupExecutor()
    controller = BenchmarkController(config, executor=executor, stop_token=stop_token)
    summary = controller.run(test_types=["stress_ng"], run_id="run-test")

    assert summary.controller_state == ControllerState.ABORTED
    assert summary.cleanup_allowed is True
