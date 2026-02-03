"""Unit tests for RunSessionBuilder."""

from pathlib import Path

import pytest

from lb_controller.engine.session_builder import RunSessionBuilder
from lb_controller.models.state import ControllerStateMachine
from lb_runner.api import BenchmarkConfig, RemoteHostConfig, WorkloadConfig

pytestmark = pytest.mark.unit_controller


def test_session_builder_creates_journal_and_refreshes(tmp_path: Path) -> None:
    config = BenchmarkConfig(
        output_dir=tmp_path / "out",
        report_dir=tmp_path / "rep",
        data_export_dir=tmp_path / "exp",
        remote_hosts=[RemoteHostConfig(name="node1", address="127.0.0.1")],
    )
    config.workloads = {"stress_ng": WorkloadConfig(plugin="stress_ng")}
    config.repetitions = 1

    state_machine = ControllerStateMachine()
    refresh_calls = {"count": 0}

    def refresh() -> None:
        refresh_calls["count"] += 1

    builder = RunSessionBuilder(
        config=config,
        state_machine=state_machine,
        stop_timeout_s=0.0,
        journal_refresh=refresh,
        collector_packages=lambda: set(),
    )

    journal_path = tmp_path / "journal.json"
    session = builder.build(
        test_types=["stress_ng"],
        run_id="run-1",
        journal=None,
        journal_path=journal_path,
    )

    assert journal_path.exists()
    assert refresh_calls["count"] == 1
    assert session.state_machine is state_machine
    assert session.state.per_host_output["node1"].exists()
