"""Tests for the SSH connectivity service."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import patch, MagicMock
import subprocess

import pytest

from lb_controller.services.connectivity_service import (
    ConnectivityService,
    ConnectivityReport,
    HostConnectivityResult,
)

pytestmark = pytest.mark.unit_controller


@dataclass
class MockRemoteHostConfig:
    """Mock host config for testing without importing full model."""

    name: str
    address: str
    port: int = 22
    user: str = "root"
    ssh_key: str | None = None
    vars: dict[str, str] | None = None


def test_empty_hosts_returns_success():
    """Empty host list should return success with no results."""
    service = ConnectivityService(timeout_seconds=5)
    report = service.check_hosts([])

    assert report.all_reachable is True
    assert report.unreachable_hosts == []
    assert report.total_count == 0
    assert report.reachable_count == 0


def test_single_host_success():
    """Successful SSH connection should be marked as reachable."""
    host = MockRemoteHostConfig(name="node1", address="192.168.1.100")

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "ok\n"
    mock_result.stderr = ""

    with patch("subprocess.run", return_value=mock_result) as mock_run:
        service = ConnectivityService(timeout_seconds=5)
        report = service.check_hosts([host])

        assert report.all_reachable is True
        assert report.total_count == 1
        assert report.reachable_count == 1
        assert len(report.results) == 1
        assert report.results[0].name == "node1"
        assert report.results[0].address == "192.168.1.100"
        assert report.results[0].reachable is True
        assert report.results[0].latency_ms is not None
        assert report.results[0].error_message is None

        # Verify SSH command was called correctly
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "ssh" in call_args
        assert "-o" in call_args
        assert "BatchMode=yes" in call_args
        assert "root@192.168.1.100" in call_args
        assert "echo ok" in call_args


def test_single_host_failure():
    """Failed SSH connection should be marked as unreachable."""
    host = MockRemoteHostConfig(name="node1", address="192.168.1.100")

    mock_result = MagicMock()
    mock_result.returncode = 255
    mock_result.stdout = ""
    mock_result.stderr = "Connection refused"

    with patch("subprocess.run", return_value=mock_result):
        service = ConnectivityService(timeout_seconds=5)
        report = service.check_hosts([host])

        assert report.all_reachable is False
        assert report.unreachable_hosts == ["node1"]
        assert report.total_count == 1
        assert report.reachable_count == 0
        assert len(report.results) == 1
        assert report.results[0].reachable is False
        assert report.results[0].error_message == "Connection refused"


def test_timeout_handling():
    """Timeout should be reported as unreachable with clear error message."""
    host = MockRemoteHostConfig(name="node1", address="192.168.1.100")

    with patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="ssh", timeout=5),
    ):
        service = ConnectivityService(timeout_seconds=5)
        report = service.check_hosts([host])

        assert report.all_reachable is False
        assert report.unreachable_hosts == ["node1"]
        assert report.results[0].reachable is False
        assert "timed out" in report.results[0].error_message.lower()


def test_ssh_key_included_when_specified():
    """SSH key path should be included in the command when specified."""
    host = MockRemoteHostConfig(
        name="node1",
        address="192.168.1.100",
        ssh_key="/home/user/.ssh/id_rsa",
    )

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "ok\n"
    mock_result.stderr = ""

    with patch("subprocess.run", return_value=mock_result) as mock_run:
        service = ConnectivityService(timeout_seconds=5)
        service.check_hosts([host])

        call_args = mock_run.call_args[0][0]
        assert "-i" in call_args
        key_index = call_args.index("-i")
        assert call_args[key_index + 1] == "/home/user/.ssh/id_rsa"


def test_ansible_ssh_private_key_file_included_when_present():
    """Ansible private key var should be included when specified."""
    host = MockRemoteHostConfig(
        name="node1",
        address="192.168.1.100",
        vars={"ansible_ssh_private_key_file": "/home/user/.ssh/ansible_key"},
    )

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "ok\n"
    mock_result.stderr = ""

    with patch("subprocess.run", return_value=mock_result) as mock_run:
        service = ConnectivityService(timeout_seconds=5)
        service.check_hosts([host])

        call_args = mock_run.call_args[0][0]
        assert "-i" in call_args
        key_index = call_args.index("-i")
        assert call_args[key_index + 1] == "/home/user/.ssh/ansible_key"


def test_custom_port_included():
    """Custom SSH port should be included in the command."""
    host = MockRemoteHostConfig(
        name="node1",
        address="192.168.1.100",
        port=2222,
    )

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "ok\n"
    mock_result.stderr = ""

    with patch("subprocess.run", return_value=mock_result) as mock_run:
        service = ConnectivityService(timeout_seconds=5)
        service.check_hosts([host])

        call_args = mock_run.call_args[0][0]
        assert "-p" in call_args
        port_index = call_args.index("-p")
        assert call_args[port_index + 1] == "2222"


def test_default_port_not_included():
    """Default SSH port (22) should not be explicitly included."""
    host = MockRemoteHostConfig(name="node1", address="192.168.1.100", port=22)

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "ok\n"
    mock_result.stderr = ""

    with patch("subprocess.run", return_value=mock_result) as mock_run:
        service = ConnectivityService(timeout_seconds=5)
        service.check_hosts([host])

        call_args = mock_run.call_args[0][0]
        assert "-p" not in call_args


def test_multiple_hosts_mixed_results():
    """Multiple hosts should each be checked independently."""
    hosts = [
        MockRemoteHostConfig(name="node1", address="192.168.1.100"),
        MockRemoteHostConfig(name="node2", address="192.168.1.101"),
        MockRemoteHostConfig(name="node3", address="192.168.1.102"),
    ]

    call_count = 0

    def mock_run(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        # First and third host succeed, second fails
        if call_count == 2:
            result.returncode = 255
            result.stdout = ""
            result.stderr = "Connection refused"
        else:
            result.returncode = 0
            result.stdout = "ok\n"
            result.stderr = ""
        return result

    with patch("subprocess.run", side_effect=mock_run):
        service = ConnectivityService(timeout_seconds=5)
        report = service.check_hosts(hosts)

        assert report.all_reachable is False
        assert report.total_count == 3
        assert report.reachable_count == 2
        assert report.unreachable_hosts == ["node2"]
        assert report.results[0].reachable is True
        assert report.results[1].reachable is False
        assert report.results[2].reachable is True


def test_connectivity_report_properties():
    """ConnectivityReport properties should work correctly."""
    results = [
        HostConnectivityResult(name="a", address="1.1.1.1", reachable=True),
        HostConnectivityResult(name="b", address="2.2.2.2", reachable=False),
        HostConnectivityResult(name="c", address="3.3.3.3", reachable=True),
    ]
    report = ConnectivityReport(results=results, timeout_seconds=10)

    assert report.all_reachable is False
    assert report.total_count == 3
    assert report.reachable_count == 2
    assert report.unreachable_hosts == ["b"]


def test_connectivity_report_all_reachable():
    """Report with all hosts reachable should have all_reachable=True."""
    results = [
        HostConnectivityResult(name="a", address="1.1.1.1", reachable=True),
        HostConnectivityResult(name="b", address="2.2.2.2", reachable=True),
    ]
    report = ConnectivityReport(results=results, timeout_seconds=10)

    assert report.all_reachable is True
    assert report.unreachable_hosts == []


def test_ssh_not_found():
    """Missing SSH client should be handled gracefully."""
    host = MockRemoteHostConfig(name="node1", address="192.168.1.100")

    with patch("subprocess.run", side_effect=FileNotFoundError("ssh not found")):
        service = ConnectivityService(timeout_seconds=5)
        report = service.check_hosts([host])

        assert report.all_reachable is False
        assert report.results[0].reachable is False
        assert "not found" in report.results[0].error_message.lower()


def test_custom_user():
    """Custom SSH user should be used in the command."""
    host = MockRemoteHostConfig(
        name="node1",
        address="192.168.1.100",
        user="ubuntu",
    )

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "ok\n"
    mock_result.stderr = ""

    with patch("subprocess.run", return_value=mock_result) as mock_run:
        service = ConnectivityService(timeout_seconds=5)
        service.check_hosts([host])

        call_args = mock_run.call_args[0][0]
        assert "ubuntu@192.168.1.100" in call_args


def test_timeout_override():
    """Timeout can be overridden per-check."""
    host = MockRemoteHostConfig(name="node1", address="192.168.1.100")

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "ok\n"
    mock_result.stderr = ""

    with patch("subprocess.run", return_value=mock_result) as mock_run:
        service = ConnectivityService(timeout_seconds=10)
        report = service.check_hosts([host], timeout_seconds=5)

        assert report.timeout_seconds == 5
        call_args = mock_run.call_args[0][0]
        assert "ConnectTimeout=5" in call_args
