"""Planning helpers for DFaaS configurations."""

from __future__ import annotations

from dataclasses import dataclass

from lb_plugins.plugins._faas_shared.plan_builder import (
    FaasPlanBuilder,
    _PlanConfigLike,
    config_id,
    config_key,
    dominates,
    generate_configurations,
    generate_function_combinations,
    generate_rates_list,
    parse_duration_seconds,
)

from ..config import DfaasConfig


@dataclass(frozen=True)
class DfaasPlanBuilder(FaasPlanBuilder):
    """Build DFaaS configuration plans from config inputs."""

    config: _PlanConfigLike


__all__ = [
    "DfaasPlanBuilder",
    "config_id",
    "config_key",
    "dominates",
    "generate_configurations",
    "generate_function_combinations",
    "generate_rates_list",
    "parse_duration_seconds",
]
