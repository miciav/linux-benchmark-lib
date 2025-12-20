"""Pass-through provisioning for already available remote hosts."""

from __future__ import annotations

from typing import List

from lb_runner.benchmark_config import RemoteHostConfig

from .types import MAX_NODES, ProvisionedNode, ProvisioningError, ProvisioningRequest


class RemoteProvisioner:
    """Return pre-configured remote hosts without side effects."""

    def provision(self, request: ProvisioningRequest) -> List[ProvisionedNode]:
        hosts = request.remote_hosts or []
        if not hosts:
            raise ProvisioningError("Remote provisioning requires remote_hosts")
        if len(hosts) > MAX_NODES:
            raise ProvisioningError(
                f"Refusing to provision more than {MAX_NODES} remote hosts"
            )
        return [ProvisionedNode(host=h) for h in hosts]
