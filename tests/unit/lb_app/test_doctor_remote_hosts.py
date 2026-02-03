"""Tests for DoctorService remote hosts connectivity check."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from lb_app.services.doctor_service import DoctorService
from lb_controller.services.connectivity_service import (
    ConnectivityReport,
    HostConnectivityResult,
)
from lb_runner.api import BenchmarkConfig, RemoteHostConfig


pytestmark = pytest.mark.unit_ui


def _make_config_with_hosts(hosts: list[RemoteHostConfig]) -> BenchmarkConfig:
    """Create a BenchmarkConfig with the given remote hosts."""
    cfg = BenchmarkConfig()
    cfg.remote_hosts = hosts
    return cfg


def test_no_hosts_configured():
    """Report should indicate no hosts when config has no remote hosts."""
    cfg = BenchmarkConfig()
    cfg.remote_hosts = []

    mock_config_service = MagicMock()
    mock_config_service.load_for_read.return_value = (cfg, None, None)

    service = DoctorService(config_service=mock_config_service)
    report = service.check_remote_hosts(config=cfg)

    assert report.total_failures == 0
    assert len(report.groups) == 0
    assert any("No remote hosts configured" in msg for msg in report.info_messages)


def test_all_hosts_reachable():
    """Report should show success when all hosts are reachable."""
    hosts = [
        RemoteHostConfig(name="node1", address="192.168.1.100"),
        RemoteHostConfig(name="node2", address="192.168.1.101"),
    ]
    cfg = _make_config_with_hosts(hosts)

    mock_connectivity_report = ConnectivityReport(
        results=[
            HostConnectivityResult(
                name="node1",
                address="192.168.1.100",
                reachable=True,
                latency_ms=10.5,
            ),
            HostConnectivityResult(
                name="node2",
                address="192.168.1.101",
                reachable=True,
                latency_ms=15.2,
            ),
        ],
        timeout_seconds=10,
    )

    with patch(
        "lb_app.services.doctor_service.ConnectivityService"
    ) as MockConnectivityService:
        mock_instance = MockConnectivityService.return_value
        mock_instance.check_hosts.return_value = mock_connectivity_report

        mock_config_service = MagicMock()
        service = DoctorService(config_service=mock_config_service)
        report = service.check_remote_hosts(config=cfg, timeout_seconds=10)

        assert report.total_failures == 0
        assert len(report.groups) == 1
        assert report.groups[0].title == "Remote Host Connectivity"
        assert len(report.groups[0].items) == 2
        assert all(item.ok for item in report.groups[0].items)
        assert any("All hosts are reachable" in msg for msg in report.info_messages)


def test_unreachable_hosts_reported():
    """Report should show failures for unreachable hosts."""
    hosts = [
        RemoteHostConfig(name="node1", address="192.168.1.100"),
        RemoteHostConfig(name="node2", address="192.168.1.101"),
    ]
    cfg = _make_config_with_hosts(hosts)

    mock_connectivity_report = ConnectivityReport(
        results=[
            HostConnectivityResult(
                name="node1",
                address="192.168.1.100",
                reachable=True,
                latency_ms=10.5,
            ),
            HostConnectivityResult(
                name="node2",
                address="192.168.1.101",
                reachable=False,
                error_message="Connection refused",
            ),
        ],
        timeout_seconds=10,
    )

    with patch(
        "lb_app.services.doctor_service.ConnectivityService"
    ) as MockConnectivityService:
        mock_instance = MockConnectivityService.return_value
        mock_instance.check_hosts.return_value = mock_connectivity_report

        mock_config_service = MagicMock()
        service = DoctorService(config_service=mock_config_service)
        report = service.check_remote_hosts(config=cfg, timeout_seconds=10)

        assert report.total_failures == 1
        assert len(report.groups) == 1
        assert len(report.groups[0].items) == 2

        # First host should be ok
        assert report.groups[0].items[0].ok is True
        assert "node1" in report.groups[0].items[0].label

        # Second host should not be ok
        assert report.groups[0].items[1].ok is False
        assert "node2" in report.groups[0].items[1].label
        assert "Connection refused" in report.groups[0].items[1].label

        # Info message should list unreachable hosts
        assert any("node2" in msg for msg in report.info_messages)


def test_loads_config_when_none_provided():
    """Should load config from config service when not provided."""
    hosts = [RemoteHostConfig(name="node1", address="192.168.1.100")]
    cfg = _make_config_with_hosts(hosts)

    mock_config_service = MagicMock()
    mock_config_service.load_for_read.return_value = (cfg, "/path/to/config", None)

    mock_connectivity_report = ConnectivityReport(
        results=[
            HostConnectivityResult(
                name="node1",
                address="192.168.1.100",
                reachable=True,
                latency_ms=5.0,
            ),
        ],
        timeout_seconds=10,
    )

    with patch(
        "lb_app.services.doctor_service.ConnectivityService"
    ) as MockConnectivityService:
        mock_instance = MockConnectivityService.return_value
        mock_instance.check_hosts.return_value = mock_connectivity_report

        service = DoctorService(config_service=mock_config_service)
        # Call without passing config
        report = service.check_remote_hosts(config=None, timeout_seconds=10)

        # Config service should have been called
        mock_config_service.load_for_read.assert_called_once_with(None)
        assert report.total_failures == 0


def test_custom_timeout_passed_to_service():
    """Custom timeout should be passed to connectivity service."""
    hosts = [RemoteHostConfig(name="node1", address="192.168.1.100")]
    cfg = _make_config_with_hosts(hosts)

    mock_connectivity_report = ConnectivityReport(
        results=[
            HostConnectivityResult(
                name="node1",
                address="192.168.1.100",
                reachable=True,
                latency_ms=5.0,
            ),
        ],
        timeout_seconds=30,
    )

    with patch(
        "lb_app.services.doctor_service.ConnectivityService"
    ) as MockConnectivityService:
        mock_instance = MockConnectivityService.return_value
        mock_instance.check_hosts.return_value = mock_connectivity_report

        mock_config_service = MagicMock()
        service = DoctorService(config_service=mock_config_service)
        report = service.check_remote_hosts(config=cfg, timeout_seconds=30)

        # Verify timeout was passed
        MockConnectivityService.assert_called_once_with(timeout_seconds=30)
        mock_instance.check_hosts.assert_called_once_with(hosts, 30)
        assert "30s timeout" in report.info_messages[0]


def test_latency_included_in_label():
    """Reachable host labels should include latency."""
    hosts = [RemoteHostConfig(name="node1", address="192.168.1.100")]
    cfg = _make_config_with_hosts(hosts)

    mock_connectivity_report = ConnectivityReport(
        results=[
            HostConnectivityResult(
                name="node1",
                address="192.168.1.100",
                reachable=True,
                latency_ms=42.5,
            ),
        ],
        timeout_seconds=10,
    )

    with patch(
        "lb_app.services.doctor_service.ConnectivityService"
    ) as MockConnectivityService:
        mock_instance = MockConnectivityService.return_value
        mock_instance.check_hosts.return_value = mock_connectivity_report

        mock_config_service = MagicMock()
        service = DoctorService(config_service=mock_config_service)
        report = service.check_remote_hosts(config=cfg, timeout_seconds=10)

        # Label should contain latency
        label = report.groups[0].items[0].label
        assert "42ms" in label or "43ms" in label  # Allow rounding
