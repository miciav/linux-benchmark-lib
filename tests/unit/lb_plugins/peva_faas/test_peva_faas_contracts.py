from __future__ import annotations

from pathlib import Path

import pytest

from lb_plugins.plugins.peva_faas.services.contracts import (
    ConfigScheduler,
    ExecutionEvent,
    MemoryEngine,
    PolicyAlgorithm,
)

pytestmark = [pytest.mark.unit_plugins]


def _event() -> ExecutionEvent:
    return ExecutionEvent(
        run_id="run-1",
        config_id="cfg-1",
        iteration=1,
        repetition=1,
        config_pairs=[("a", 10)],
        config_key=(("a",), (10,)),
        started_at=1.0,
        ended_at=2.0,
        result_row={"ok": True},
        metrics={},
        summary={},
        output_dir=Path("/tmp"),
    )


class _Scheduler:
    def propose_batch(self, *, candidates, seen_keys, desired_size):
        if desired_size <= 0:
            return []
        return [cfg for cfg in candidates if tuple(cfg) and len(cfg) > 0][:desired_size]


class _Policy:
    def choose_batch(self, *, candidates, desired_size):
        return candidates[:desired_size]

    def update_online(self, event):
        _ = event

    def update_batch(self, events):
        _ = events


class _Memory:
    def startup(self):
        return None

    def is_seen(self, key):
        _ = key
        return False

    def ingest_event(self, event):
        _ = event

    def checkpoint(self):
        return None


def test_protocol_conformance_runtime() -> None:
    scheduler = _Scheduler()
    policy = _Policy()
    memory = _Memory()

    assert isinstance(scheduler, ConfigScheduler)
    assert isinstance(policy, PolicyAlgorithm)
    assert isinstance(memory, MemoryEngine)

    policy.update_online(_event())
    policy.update_batch([_event()])
    memory.ingest_event(_event())
