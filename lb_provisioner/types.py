"""Shared provisioning types and value objects."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, List, Optional

from lb_runner.benchmark_config import RemoteHostConfig

MAX_NODES = 2


class ProvisioningMode(str, Enum):
    """Supported provisioning strategies."""

    REMOTE = "remote"
    DOCKER = "docker"
    MULTIPASS = "multipass"


@dataclass
class ProvisioningRequest:
    """Input required to provision one or more nodes."""

    mode: ProvisioningMode
    count: int = 1
    remote_hosts: Optional[List[RemoteHostConfig]] = None
    docker_engine: str = "docker"
    docker_image: str = "ubuntu:24.04"
    multipass_image: str = "24.04"
    state_dir: Optional[Path] = None


@dataclass
class ProvisionedNode:
    """Provisioned host plus a teardown hook."""

    host: RemoteHostConfig
    destroy: Optional[Callable[[], None]] = None

    def teardown(self) -> None:
        """Destroy this node if a hook is available."""
        if self.destroy:
            try:
                self.destroy()
            except Exception:
                # Best-effort cleanup; callers should not fail on teardown.
                pass


@dataclass
class ProvisioningResult:
    """Aggregate provisioning outcome."""

    nodes: List[ProvisionedNode]

    def destroy_all(self) -> None:
        """Destroy all provisioned nodes in best-effort fashion."""
        for node in self.nodes:
            node.teardown()


class ProvisioningError(Exception):
    """Raised when provisioning fails."""

    pass
