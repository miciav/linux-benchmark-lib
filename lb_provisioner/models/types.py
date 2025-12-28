"""Shared provisioning types and value objects."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, List, Optional

from lb_common.api import RemoteHostSpec

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
    remote_hosts: Optional[List[RemoteHostSpec]] = None
    node_names: Optional[List[str]] = None
    docker_engine: str = "docker"
    docker_image: str = "ubuntu:24.04"
    multipass_image: str = "24.04"
    state_dir: Optional[Path] = None


@dataclass
class ProvisionedNode:
    """Provisioned host plus a teardown hook."""

    host: RemoteHostSpec
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
    keep_nodes: bool = False

    def destroy_all(self) -> None:
        """Destroy all provisioned nodes in best-effort fashion."""
        if self.keep_nodes:
            return
        for node in self.nodes:
            node.teardown()


class ProvisioningError(Exception):
    """Raised when provisioning fails."""

    pass
