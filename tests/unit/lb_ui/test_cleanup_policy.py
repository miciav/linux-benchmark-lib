"""Tests for provisioning cleanup policy driven by controller state."""

from types import SimpleNamespace

import pytest

from lb_controller.api import ControllerState, RunExecutionSummary
from lb_provisioner.types import ProvisionedNode, ProvisioningResult
from lb_runner.benchmark_config import RemoteHostConfig
from lb_ui.cli import _cleanup_provisioned_nodes


class DummyPresenter:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def warning(self, msg: str) -> None:
        self.warnings.append(msg)


def _make_summary(tmp_path, cleanup_allowed: bool, success: bool = True) -> RunExecutionSummary:
    return RunExecutionSummary(
        run_id="test",
        per_host_output={},
        phases={},
        success=success,
        output_root=tmp_path / "out",
        report_root=tmp_path / "rep",
        data_export_root=tmp_path / "data",
        controller_state=ControllerState.FINISHED if success else ControllerState.FAILED,
        cleanup_allowed=cleanup_allowed,
    )


def test_cleanup_skipped_when_not_authorized(tmp_path):
    destroyed: list[str] = []
    presenter = DummyPresenter()
    node = ProvisionedNode(
        host=RemoteHostConfig(name="n1", address="127.0.0.1"),
        destroy=lambda: destroyed.append("x"),
    )
    provisioning = ProvisioningResult(nodes=[node])
    summary = _make_summary(tmp_path, cleanup_allowed=False)
    result = SimpleNamespace(summary=summary)

    _cleanup_provisioned_nodes(provisioning, result, presenter)

    assert provisioning.keep_nodes is True
    assert destroyed == []
    assert any("authorize" in msg.lower() for msg in presenter.warnings)


def test_cleanup_runs_when_authorized(tmp_path):
    destroyed: list[str] = []
    presenter = DummyPresenter()
    node = ProvisionedNode(
        host=RemoteHostConfig(name="n1", address="127.0.0.1"),
        destroy=lambda: destroyed.append("x"),
    )
    provisioning = ProvisioningResult(nodes=[node])
    summary = _make_summary(tmp_path, cleanup_allowed=True)
    result = SimpleNamespace(summary=summary)

    _cleanup_provisioned_nodes(provisioning, result, presenter)

    assert provisioning.keep_nodes is False
    assert destroyed == ["x"]
    assert presenter.warnings == []
