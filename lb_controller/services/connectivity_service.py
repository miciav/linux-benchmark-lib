"""
Service for checking SSH connectivity to remote hosts.

Provides fast pre-flight checks to avoid waiting for Ansible timeouts
when hosts are unreachable.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lb_controller.models.contracts import RemoteHostConfig


@dataclass
class HostConnectivityResult:
    """Result of a connectivity check for a single host."""

    name: str
    address: str
    reachable: bool
    latency_ms: float | None = None
    error_message: str | None = None


@dataclass
class ConnectivityReport:
    """Aggregated report of connectivity checks for multiple hosts."""

    results: list[HostConnectivityResult] = field(default_factory=list)
    timeout_seconds: int = 10

    @property
    def all_reachable(self) -> bool:
        """Return True if all hosts are reachable."""
        return all(r.reachable for r in self.results)

    @property
    def unreachable_hosts(self) -> list[str]:
        """Return list of unreachable host names."""
        return [r.name for r in self.results if not r.reachable]

    @property
    def reachable_count(self) -> int:
        """Return count of reachable hosts."""
        return sum(1 for r in self.results if r.reachable)

    @property
    def total_count(self) -> int:
        """Return total number of hosts checked."""
        return len(self.results)


class ConnectivityService:
    """Service for checking SSH connectivity to remote hosts."""

    DEFAULT_TIMEOUT_SECONDS = 10

    def __init__(self, timeout_seconds: int | None = None) -> None:
        """Initialize the connectivity service.

        Args:
            timeout_seconds: Default timeout for connectivity checks.
                Defaults to 10 seconds.
        """
        self._timeout_seconds = timeout_seconds or self.DEFAULT_TIMEOUT_SECONDS

    def check_hosts(
        self,
        hosts: list[RemoteHostConfig],
        timeout_seconds: int | None = None,
    ) -> ConnectivityReport:
        """Check connectivity to all specified hosts.

        Args:
            hosts: List of remote host configurations to check.
            timeout_seconds: Optional timeout override for this check.

        Returns:
            ConnectivityReport with results for each host.
        """
        timeout = timeout_seconds or self._timeout_seconds
        results = []

        for host in hosts:
            result = self._check_single_host(host, timeout)
            results.append(result)

        return ConnectivityReport(results=results, timeout_seconds=timeout)

    def _check_single_host(
        self,
        host: RemoteHostConfig,
        timeout: int,
    ) -> HostConnectivityResult:
        """Check SSH connectivity to a single host.

        Uses direct SSH with BatchMode to quickly verify connectivity
        without interactive prompts.

        Args:
            host: Remote host configuration.
            timeout: Timeout in seconds for the connection attempt.

        Returns:
            HostConnectivityResult with connectivity status.
        """
        start_time = time.time()
        address = host.address
        ssh_cmd = _build_ssh_command(host, timeout, address)

        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                timeout=timeout + 5,  # Give a bit more time than SSH timeout
            )
        except subprocess.TimeoutExpired:
            return _timeout_result(host, address, start_time, timeout)
        except FileNotFoundError:
            return _error_result(
                host, address, "SSH client not found in PATH"
            )
        except Exception as exc:
            return _error_result(host, address, str(exc), start_time)

        elapsed_ms = _elapsed_ms(start_time)
        if result.returncode == 0 and "ok" in result.stdout:
            return _success_result(host, address, elapsed_ms)
        error_msg = result.stderr.strip() or f"SSH exit code: {result.returncode}"
        return _error_result(host, address, error_msg, start_time)


def _build_ssh_command(
    host: RemoteHostConfig, timeout: int, address: str
) -> list[str]:
    ssh_cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={timeout}",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "LogLevel=ERROR",
    ]
    port = getattr(host, "port", None) or 22
    if port != 22:
        ssh_cmd.extend(["-p", str(port)])
    ssh_key = _resolve_ssh_key(host)
    if ssh_key:
        ssh_cmd.extend(["-i", str(ssh_key)])
    user = getattr(host, "user", None) or "root"
    ssh_cmd.append(f"{user}@{address}")
    ssh_cmd.append("echo ok")
    return ssh_cmd


def _resolve_ssh_key(host: RemoteHostConfig) -> str | None:
    ssh_key = getattr(host, "ssh_key", None) or getattr(host, "key_file", None)
    if ssh_key:
        return str(ssh_key)
    vars_map = getattr(host, "vars", None) or {}
    if isinstance(vars_map, dict):
        return vars_map.get("ansible_ssh_private_key_file")
    return None


def _elapsed_ms(start_time: float) -> float:
    return (time.time() - start_time) * 1000


def _success_result(
    host: RemoteHostConfig, address: str, elapsed_ms: float
) -> HostConnectivityResult:
    return HostConnectivityResult(
        name=host.name,
        address=address,
        reachable=True,
        latency_ms=round(elapsed_ms, 2),
    )


def _timeout_result(
    host: RemoteHostConfig,
    address: str,
    start_time: float,
    timeout: int,
) -> HostConnectivityResult:
    return HostConnectivityResult(
        name=host.name,
        address=address,
        reachable=False,
        latency_ms=round(_elapsed_ms(start_time), 2),
        error_message=f"Connection timed out after {timeout}s",
    )


def _error_result(
    host: RemoteHostConfig,
    address: str,
    error_message: str,
    start_time: float | None = None,
) -> HostConnectivityResult:
    latency_ms = round(_elapsed_ms(start_time), 2) if start_time else None
    return HostConnectivityResult(
        name=host.name,
        address=address,
        reachable=False,
        latency_ms=latency_ms,
        error_message=error_message,
    )
