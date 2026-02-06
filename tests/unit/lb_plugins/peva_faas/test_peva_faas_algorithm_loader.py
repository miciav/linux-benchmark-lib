from __future__ import annotations

import pytest

from lb_plugins.plugins.peva_faas.services.algorithm_loader import (
    NoOpPolicy,
    load_policy_algorithm,
)

pytestmark = [pytest.mark.unit_plugins]


def test_default_algorithm_is_noop_policy() -> None:
    policy = load_policy_algorithm(None)
    assert isinstance(policy, NoOpPolicy)


def test_custom_entrypoint_loads_algorithm() -> None:
    policy = load_policy_algorithm(
        "tests.unit.lb_plugins.peva_faas.fixtures.custom_algo:CustomPolicy"
    )
    assert policy.__class__.__name__ == "CustomPolicy"
