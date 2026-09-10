"""Shared provisioning types and value objects."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

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
    remote_hosts: list[RemoteHostSpec] | None = None
    node_names: list[str] | None = None
    docker_engine: str = "docker"
    docker_image: str = "ubuntu:24.04"
    multipass_image: str = "24.04"
    state_dir: Path | None = None


@dataclass
class ProvisionedNode:
    """Provisioned host plus a teardown hook."""

    host: RemoteHostSpec
    destroy: Callable[[], None] | None = None

    def teardown(self) -> None:
        """Destroy this node if a hook is available."""
        if self.destroy:
            with contextlib.suppress(Exception):
                # Best-effort cleanup; callers should not fail on teardown.
                self.destroy()


@dataclass
class ProvisioningResult:
    """Aggregate provisioning outcome."""

    nodes: list[ProvisionedNode]
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
