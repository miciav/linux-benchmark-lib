"""Unified provisioning facade for linux-benchmark-lib."""

from lb_common.api import configure_logging as _configure_logging

_configure_logging()

from lb_provisioner.api import (  # noqa: F401
    ProvisionedNode,
    ProvisioningError,
    ProvisioningMode,
    ProvisioningRequest,
    ProvisioningResult,
    cleanup_provisioned_nodes,
    ProvisioningService,
    MAX_NODES,
)

__all__ = [
    "ProvisioningError",
    "ProvisioningMode",
    "ProvisioningRequest",
    "ProvisionedNode",
    "ProvisioningResult",
    "cleanup_provisioned_nodes",
    "ProvisioningService",
    "MAX_NODES",
]
