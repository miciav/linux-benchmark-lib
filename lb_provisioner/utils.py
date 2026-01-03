from __future__ import annotations

import logging

from lb_provisioner.types import ProvisioningResult


logger = logging.getLogger(__name__)
teardown_logger = logging.LoggerAdapter(logger, {"lb_phase": "teardown"})


def cleanup_provisioned_nodes(provisioning_result: ProvisioningResult, result, presenter) -> None:
    """
    Apply cleanup policy using controller authorization.

    Expects `result.summary.cleanup_allowed` to indicate permission to teardown.
    """
    if not provisioning_result:
        return
    allow_cleanup = bool(result and getattr(result, "summary", None) and getattr(result.summary, "cleanup_allowed", False))
    if result and getattr(result, "summary", None) and not getattr(result.summary, "success", True):
        presenter.warning("Run failed; preserving provisioned nodes for inspection.")
        teardown_logger.warning("Run failed; preserving provisioned nodes for inspection.")
        provisioning_result.keep_nodes = True
    if not allow_cleanup:
        presenter.warning("Controller did not authorize cleanup; provisioned nodes preserved.")
        teardown_logger.warning("Controller did not authorize cleanup; provisioned nodes preserved.")
        provisioning_result.keep_nodes = True
    provisioning_result.destroy_all()


__all__ = ["cleanup_provisioned_nodes"]
