"""Facade that routes provisioning requests to the correct backend."""

from __future__ import annotations

import inspect
import logging
import os
from typing import List

from lb_provisioner.providers.docker import DockerProvisioner
from lb_provisioner.providers.multipass import MultipassProvisioner
from lb_provisioner.providers.remote import RemoteProvisioner
from lb_provisioner.models.types import (
    ProvisionedNode,
    ProvisioningError,
    ProvisioningMode,
    ProvisioningRequest,
    ProvisioningResult,
)

logger = logging.getLogger(__name__)


class ProvisioningService:
    """Provision nodes across remote, docker, and multipass modes."""

    def __init__(
        self,
        enforce_ui_caller: bool = True,
        allowed_callers: tuple[str, ...] = ("lb_ui",),
    ):
        self._docker = DockerProvisioner()
        self._multipass = MultipassProvisioner()
        self._remote = RemoteProvisioner()
        self._enforce_ui_caller = enforce_ui_caller
        self._allowed_callers = allowed_callers
        if enforce_ui_caller:
            self._assert_ui_caller()

    def provision(self, request: ProvisioningRequest) -> ProvisioningResult:
        """Provision resources according to the request."""
        self._enforce_limits(request.count)
        self._assert_ui_caller()

        if request.mode is ProvisioningMode.REMOTE:
            nodes = self._remote.provision(request)
        elif request.mode is ProvisioningMode.DOCKER:
            nodes = self._docker.provision(request)
        elif request.mode is ProvisioningMode.MULTIPASS:
            nodes = self._multipass.provision(request)
        else:  # pragma: no cover - defensive
            raise ProvisioningError(f"Unsupported provisioning mode: {request.mode}")

        return ProvisioningResult(nodes=nodes)

    def _enforce_limits(self, requested: int) -> None:
        if requested > MAX_NODES:
            raise ProvisioningError(
                f"Maximum number of provisioned nodes is {MAX_NODES} (requested {requested})"
            )

    def _assert_ui_caller(self) -> None:
        """Ensure the service is invoked from lb_ui unless explicitly disabled."""
        if not self._enforce_ui_caller:
            return
        if os.getenv("LB_PROVISIONER_ALLOW_NON_UI") == "1":
            return

        for frame in inspect.stack():
            for marker in self._allowed_callers:
                if marker in frame.filename or frame.function.startswith(marker):
                    return

        raise PermissionError("lb_provisioner can only be invoked from lb_ui")
