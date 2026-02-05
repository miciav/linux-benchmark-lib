"""Tests for remote host configuration management."""

from __future__ import annotations

from pathlib import Path

import pytest

from lb_app.services.config_service import ConfigService
from lb_runner.api import BenchmarkConfig, RemoteHostConfig


pytestmark = pytest.mark.unit_ui


def test_add_remote_host_creates_new(tmp_path: Path) -> None:
    """Adding a host to empty config should create the host entry."""
    service = ConfigService(config_home=tmp_path)
    config_path = tmp_path / "config.json"

    # Create initial empty config
    cfg = BenchmarkConfig()
    cfg.save(config_path)

    host = RemoteHostConfig(
        name="node1",
        address="192.168.1.100",
        port=22,
        user="ubuntu",
    )

    result_cfg, target, stale = service.add_remote_host(host, config_path)

    assert len(result_cfg.remote_hosts) == 1
    assert result_cfg.remote_hosts[0].name == "node1"
    assert result_cfg.remote_hosts[0].address == "192.168.1.100"
    assert result_cfg.remote_execution.enabled is True
    assert target == config_path


def test_add_remote_host_replaces_existing(tmp_path: Path) -> None:
    """Adding a host with same name should replace the existing one."""
    service = ConfigService(config_home=tmp_path)
    config_path = tmp_path / "config.json"

    # Create config with one host
    cfg = BenchmarkConfig()
    cfg.remote_hosts = [RemoteHostConfig(name="node1", address="192.168.1.100")]
    cfg.save(config_path)

    # Add host with same name but different address
    new_host = RemoteHostConfig(
        name="node1",
        address="192.168.1.200",  # Different address
        port=2222,
    )

    result_cfg, _, _ = service.add_remote_host(new_host, config_path)

    assert len(result_cfg.remote_hosts) == 1
    assert result_cfg.remote_hosts[0].address == "192.168.1.200"
    assert result_cfg.remote_hosts[0].port == 2222


def test_add_remote_host_appends_to_existing(tmp_path: Path) -> None:
    """Adding a host with different name should append to list."""
    service = ConfigService(config_home=tmp_path)
    config_path = tmp_path / "config.json"

    cfg = BenchmarkConfig()
    cfg.remote_hosts = [RemoteHostConfig(name="node1", address="192.168.1.100")]
    cfg.save(config_path)

    new_host = RemoteHostConfig(name="node2", address="192.168.1.101")
    result_cfg, _, _ = service.add_remote_host(new_host, config_path)

    assert len(result_cfg.remote_hosts) == 2
    names = [h.name for h in result_cfg.remote_hosts]
    assert "node1" in names
    assert "node2" in names


def test_add_remote_host_with_custom_port(tmp_path: Path) -> None:
    """Adding a host with custom port should preserve the port."""
    service = ConfigService(config_home=tmp_path)
    config_path = tmp_path / "config.json"

    cfg = BenchmarkConfig()
    cfg.save(config_path)

    host = RemoteHostConfig(
        name="node1",
        address="192.168.1.100",
        port=2222,
    )

    result_cfg, _, _ = service.add_remote_host(host, config_path)

    assert result_cfg.remote_hosts[0].port == 2222


def test_remove_remote_host_existing(tmp_path: Path) -> None:
    """Removing an existing host should remove it and return removed=True."""
    service = ConfigService(config_home=tmp_path)
    config_path = tmp_path / "config.json"

    cfg = BenchmarkConfig()
    cfg.remote_hosts = [
        RemoteHostConfig(name="node1", address="192.168.1.100"),
        RemoteHostConfig(name="node2", address="192.168.1.101"),
    ]
    cfg.remote_execution.enabled = True
    cfg.save(config_path)

    result_cfg, _, _, removed = service.remove_remote_host("node1", config_path)

    assert removed is True
    assert len(result_cfg.remote_hosts) == 1
    assert result_cfg.remote_hosts[0].name == "node2"
    assert result_cfg.remote_execution.enabled is True  # Still has hosts


def test_remove_remote_host_nonexistent(tmp_path: Path) -> None:
    """Removing a non-existent host should return removed=False."""
    service = ConfigService(config_home=tmp_path)
    config_path = tmp_path / "config.json"

    cfg = BenchmarkConfig()
    cfg.remote_hosts = [
        RemoteHostConfig(name="node1", address="192.168.1.100"),
    ]
    cfg.save(config_path)

    result_cfg, _, _, removed = service.remove_remote_host("nonexistent", config_path)

    assert removed is False
    assert len(result_cfg.remote_hosts) == 1


def test_remove_last_host_disables_remote_execution(tmp_path: Path) -> None:
    """Removing the last host should disable remote execution."""
    service = ConfigService(config_home=tmp_path)
    config_path = tmp_path / "config.json"

    cfg = BenchmarkConfig()
    cfg.remote_hosts = [
        RemoteHostConfig(name="node1", address="192.168.1.100"),
    ]
    cfg.remote_execution.enabled = True
    cfg.save(config_path)

    result_cfg, _, _, removed = service.remove_remote_host("node1", config_path)

    assert removed is True
    assert len(result_cfg.remote_hosts) == 0
    assert result_cfg.remote_execution.enabled is False


def test_remove_remote_host_no_config_raises(tmp_path: Path) -> None:
    """Removing a host when no config exists should raise FileNotFoundError."""
    service = ConfigService(config_home=tmp_path)
    config_path = tmp_path / "nonexistent.json"

    with pytest.raises(FileNotFoundError):
        service.remove_remote_host("node1", config_path)


def test_add_host_with_vars(tmp_path: Path) -> None:
    """Adding a host with custom vars should preserve them."""
    service = ConfigService(config_home=tmp_path)
    config_path = tmp_path / "config.json"

    cfg = BenchmarkConfig()
    cfg.save(config_path)

    host = RemoteHostConfig(
        name="node1",
        address="192.168.1.100",
        vars={
            "ansible_ssh_private_key_file": "/path/to/key",
            "ansible_ssh_common_args": "-o StrictHostKeyChecking=no",
        },
    )

    result_cfg, _, _ = service.add_remote_host(host, config_path)

    assert "ansible_ssh_private_key_file" in result_cfg.remote_hosts[0].vars
    assert (
        result_cfg.remote_hosts[0].vars["ansible_ssh_private_key_file"]
        == "/path/to/key"
    )
