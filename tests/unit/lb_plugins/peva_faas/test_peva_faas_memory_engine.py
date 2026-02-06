from __future__ import annotations

from pathlib import Path

import pytest

from lb_plugins.plugins.peva_faas.services.contracts import ExecutionEvent
from lb_plugins.plugins.peva_faas.services.memory_engine import InProcessMemoryEngine
from lb_plugins.plugins.peva_faas.services.memory_store import DuckDBMemoryStore
from lb_plugins.plugins.peva_faas.services.tensor_cache import TensorCache

pytestmark = [pytest.mark.unit_plugins]


class _PolicySpy:
    def __init__(self) -> None:
        self.online_calls = 0
        self.batch_calls = 0
        self.last_batch_size = 0

    def choose_batch(self, *, candidates, desired_size):
        return candidates[:desired_size]

    def update_online(self, event: ExecutionEvent) -> None:
        _ = event
        self.online_calls += 1

    def update_batch(self, events: list[ExecutionEvent]) -> None:
        self.batch_calls += 1
        self.last_batch_size = len(events)


def _event(config_id: str, config_key):
    return ExecutionEvent(
        run_id="run-1",
        config_id=config_id,
        iteration=1,
        repetition=1,
        config_pairs=[("a", 10)],
        config_key=config_key,
        started_at=1.0,
        ended_at=2.0,
        result_row={"overloaded_node": 0, "rest_seconds": 1},
        metrics={"cpu_usage_node": 12.3},
        summary={"metrics": {}},
        output_dir=Path("/tmp"),
    )


def test_ingest_updates_store_and_hot_cache(tmp_path: Path) -> None:
    store = DuckDBMemoryStore(tmp_path / "memory.duckdb", "peva_faas_mem_v1")
    policy = _PolicySpy()
    engine = InProcessMemoryEngine(
        mode="online",
        batch_size=2,
        batch_window_s=30,
        store=store,
        cache=TensorCache(),
        policy=policy,
    )
    engine.startup()
    key = (("a",), (10,))

    engine.ingest_event(_event("cfg-1", key))

    assert engine.is_seen(key) is True
    assert engine.tensor_cache_size() == 1
    assert store.count_execution_events() == 1


def test_online_mode_triggers_policy_update_per_event(tmp_path: Path) -> None:
    store = DuckDBMemoryStore(tmp_path / "memory.duckdb", "peva_faas_mem_v1")
    policy = _PolicySpy()
    engine = InProcessMemoryEngine(
        mode="online",
        batch_size=2,
        batch_window_s=30,
        store=store,
        cache=TensorCache(),
        policy=policy,
    )
    engine.startup()

    engine.ingest_event(_event("cfg-1", (("a",), (10,))))

    assert policy.online_calls == 1
    assert policy.batch_calls == 0


def test_micro_batch_mode_triggers_policy_update_by_threshold(tmp_path: Path) -> None:
    store = DuckDBMemoryStore(tmp_path / "memory.duckdb", "peva_faas_mem_v1")
    policy = _PolicySpy()
    engine = InProcessMemoryEngine(
        mode="micro_batch",
        batch_size=2,
        batch_window_s=300,
        store=store,
        cache=TensorCache(),
        policy=policy,
    )
    engine.startup()

    engine.ingest_event(_event("cfg-1", (("a",), (10,))))
    assert policy.batch_calls == 0
    engine.ingest_event(_event("cfg-2", (("a",), (20,))))

    assert policy.batch_calls == 1
    assert policy.last_batch_size == 2
