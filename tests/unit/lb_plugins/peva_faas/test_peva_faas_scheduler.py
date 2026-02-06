from __future__ import annotations

import pytest

from lb_plugins.plugins.peva_faas.services.cartesian_scheduler import CartesianScheduler
from lb_plugins.plugins.peva_faas.services.plan_builder import config_key

pytestmark = [pytest.mark.unit_plugins]


def test_cartesian_scheduler_matches_existing_order() -> None:
    candidates = [
        [("a", 0)],
        [("a", 10)],
        [("b", 0)],
        [("b", 10)],
        [("a", 0), ("b", 0)],
    ]
    scheduler = CartesianScheduler()

    batch = scheduler.propose_batch(
        candidates=candidates, seen_keys=set(), desired_size=4
    )

    assert batch == [
        [("a", 0)],
        [("a", 10)],
        [("b", 0)],
        [("b", 10)],
    ]


def test_scheduler_skips_seen_without_replacement() -> None:
    candidates = [
        [("a", 0)],
        [("a", 10)],
        [("b", 0)],
    ]
    seen = {config_key([("a", 10)])}
    scheduler = CartesianScheduler()

    batch = scheduler.propose_batch(candidates=candidates, seen_keys=seen, desired_size=3)

    assert batch == [
        [("a", 0)],
        [("b", 0)],
    ]
