"""Unit tests for RunOrchestrator."""

from pathlib import Path

import pytest

from typing import Callable

from lb_controller.engine.run_state import RunFlags, RunState
from lb_controller.engine.session_builder import RunSessionBuilder
from lb_controller.engine.session import RunSession
from lb_controller.models.state import ControllerStateMachine, ControllerState
from lb_controller.models.types import ExecutionResult, InventorySpec
from lb_controller.services.run_orchestrator import RunOrchestrator
from lb_controller.services.services import ControllerServices
from lb_controller.services.ui_notifier import UINotifier
from lb_runner.api import BenchmarkConfig, RemoteHostConfig, WorkloadConfig

pytestmark = pytest.mark.unit_controller


class DummyExecutor:
    """RemoteExecutor stub for orchestrator tests."""

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
        return ExecutionResult(rc=0, status="successful")


class DummyWorkloadRunner:
    """Workload runner stub that records invocation."""

    def __init__(self) -> None:
        self.called = False
        self.resume_requested = None

    def run_workloads(
        self,
        services: ControllerServices,
        session: RunSession,
        state: RunState,
        phases: dict[str, ExecutionResult],
        flags: RunFlags,
        resume_requested: bool,
        ui_log: Callable[[str], None],
    ) -> RunFlags:
        self.called = True
        self.resume_requested = resume_requested
        return flags


class DummyTeardownService:
    """Teardown stub that records invocation."""

    def __init__(self) -> None:
        self.called = False

    def run_global_teardown(
        self,
        services: ControllerServices,
        session: RunSession,
        state: RunState,
        phases: dict[str, ExecutionResult],
        flags: RunFlags,
        ui_log: Callable[[str], None],
    ) -> None:
        self.called = True
        session.transition(ControllerState.RUNNING_GLOBAL_TEARDOWN)


def test_orchestrator_runs_workloads_and_teardown(tmp_path: Path) -> None:
    config = BenchmarkConfig(
        output_dir=tmp_path / "out",
        report_dir=tmp_path / "rep",
        data_export_dir=tmp_path / "exp",
        remote_hosts=[RemoteHostConfig(name="node1", address="127.0.0.1")],
    )
    config.workloads = {"stress_ng": WorkloadConfig(plugin="stress_ng")}
    config.repetitions = 1
    config.remote_execution.run_setup = False

    services = ControllerServices(config=config, executor=DummyExecutor())
    ui_notifier = UINotifier()
    workload_runner = DummyWorkloadRunner()
    teardown_service = DummyTeardownService()

    builder = RunSessionBuilder(
        config=config,
        state_machine=ControllerStateMachine(),
        stop_timeout_s=0.0,
        journal_refresh=None,
        collector_packages=lambda: set(),
    )
    session = builder.build(
        test_types=["stress_ng"],
        run_id="run-2",
        journal=None,
        journal_path=None,
    )

    orchestrator = RunOrchestrator(
        services=services,
        workload_runner=workload_runner,
        teardown_service=teardown_service,
        ui_notifier=ui_notifier,
    )

    summary = orchestrator.run(session, resume_requested=False)

    assert workload_runner.called
    assert workload_runner.resume_requested is False
    assert teardown_service.called
    assert summary.run_id == "run-2"
    assert summary.controller_state == ControllerState.FINISHED
