# PEVA-FAAS Memory And Extensibility Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an ML/RL-ready in-process memory subsystem for `peva_faas` with online and micro-batch modes, while preserving current cartesian behavior as default and introducing generic extension points for custom algorithms.

**Architecture:** Introduce dependency-inverted contracts for scheduling, policy, and memory (`interfaces -> implementations`). Keep `DfaasGenerator` orchestration stable and move selection/state logic behind abstractions. Use DuckDB as source of truth, RAM tensor cache for hot path decisions, and Parquet checkpoints for preload/export with strict schema versioning.

**Tech Stack:** Python 3.12+, Pydantic v2, DuckDB, PyArrow/Parquet, NumPy, pytest.

## Engineering Principles

- Follow @superpowers:test-driven-development for every behavior change.
- Keep runtime behavior backward-compatible by default (`cartesian`, sequential execution, skip-without-replacement).
- Use SOLID: `run_execution` depends on interfaces, not concrete implementations.
- Keep raw k6 summaries in separate debug archive; do not preload them by default.
- Enforce strict schema version for preload/import.

### Task 1: Add Config Surface For Memory, Modes, And Extensibility

**Files:**
- Modify: `lb_plugins/plugins/peva_faas/config.py`
- Test: `tests/unit/lb_plugins/peva_faas/test_peva_faas_config.py`

**Step 1: Write the failing tests**

```python
def test_memory_defaults_use_duckdb_and_core_preload_only() -> None:
    cfg = DfaasConfig()
    assert cfg.memory.backend == "duckdb"
    assert cfg.memory.preload_raw_debug is False


def test_micro_batch_requires_positive_batch_size() -> None:
    with pytest.raises(ValidationError):
        DfaasConfig(selection_mode="micro_batch", micro_batch_size=0)


def test_custom_algorithm_entrypoint_is_optional() -> None:
    cfg = DfaasConfig()
    assert cfg.algorithm_entrypoint is None
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_peva_faas_config.py -q`
Expected: FAIL due to missing fields/validation.

**Step 3: Write minimal implementation**

```python
class MemoryConfig(BaseModel):
    backend: Literal["duckdb"] = "duckdb"
    db_path: str = "benchmark_results/peva_faas/memory/peva_faas.duckdb"
    preload_core_parquet_dir: str | None = None
    export_core_parquet_dir: str | None = None
    export_raw_debug_parquet_dir: str | None = None
    preload_raw_debug: bool = False
    schema_version: str = "peva_faas_mem_v1"


class DfaasConfig(BasePluginConfig):
    selection_mode: Literal["online", "micro_batch"] = "online"
    micro_batch_size: int = 8
    micro_batch_window_s: int = 30
    algorithm_entrypoint: str | None = None
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
```

Add validators:
- `micro_batch_size >= 1` when `selection_mode == "micro_batch"`
- `micro_batch_window_s >= 1` when `selection_mode == "micro_batch"`

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_peva_faas_config.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add lb_plugins/plugins/peva_faas/config.py tests/unit/lb_plugins/peva_faas/test_peva_faas_config.py
git commit -m "feat(peva_faas): add memory and selection config surface"
```

### Task 2: Introduce Generic Contracts (Scheduler, Policy, Memory)

**Files:**
- Create: `lb_plugins/plugins/peva_faas/services/contracts.py`
- Create: `tests/unit/lb_plugins/peva_faas/test_peva_faas_contracts.py`

**Step 1: Write failing tests**

```python
def test_default_components_satisfy_contracts() -> None:
    scheduler = CartesianScheduler()
    policy = NoOpPolicy()
    memory = InProcessMemoryEngine(...)
    assert isinstance(scheduler, ConfigScheduler)
    assert isinstance(policy, PolicyAlgorithm)
    assert isinstance(memory, MemoryEngine)
```

**Step 2: Run failing tests**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_peva_faas_contracts.py -q`
Expected: FAIL missing contracts/classes.

**Step 3: Minimal implementation**

```python
class ConfigScheduler(Protocol):
    def propose_batch(self, *, ctx: "DfaasRunContext", desired_size: int) -> list[list[tuple[str, int]]]: ...

class PolicyAlgorithm(Protocol):
    def choose_batch(self, *, candidates: list[list[tuple[str, int]]], desired_size: int) -> list[list[tuple[str, int]]]: ...
    def update_online(self, event: "ExecutionEvent") -> None: ...
    def update_batch(self, events: list["ExecutionEvent"]) -> None: ...

class MemoryEngine(Protocol):
    def startup(self) -> None: ...
    def is_seen(self, key: tuple[tuple[str, ...], tuple[int, ...]]) -> bool: ...
    def ingest_event(self, event: "ExecutionEvent") -> None: ...
    def checkpoint(self) -> None: ...
```

**Step 4: Run tests to green**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_peva_faas_contracts.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add lb_plugins/plugins/peva_faas/services/contracts.py tests/unit/lb_plugins/peva_faas/test_peva_faas_contracts.py
git commit -m "feat(peva_faas): add scheduling/policy/memory contracts"
```

### Task 3: Extract Cartesian Scheduler As Default Strategy

**Files:**
- Create: `lb_plugins/plugins/peva_faas/services/cartesian_scheduler.py`
- Modify: `lb_plugins/plugins/peva_faas/services/plan_builder.py`
- Test: `tests/unit/lb_plugins/peva_faas/test_peva_faas_generator.py`
- Test: `tests/unit/lb_plugins/peva_faas/test_peva_faas_scheduler.py`

**Step 1: Write failing tests**

```python
def test_cartesian_scheduler_matches_existing_order() -> None:
    scheduler = CartesianScheduler(plan_builder)
    batch = scheduler.propose_batch(ctx=ctx, desired_size=4)
    assert batch == expected_first_four_configs


def test_scheduler_skip_seen_without_replacement() -> None:
    ctx.existing_index.add(config_key([("a", 10)]))
    batch = scheduler.propose_batch(ctx=ctx, desired_size=3)
    assert len(batch) <= 3
    assert [("a", 10)] not in batch
```

**Step 2: Run test to fail**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_peva_faas_scheduler.py -q`
Expected: FAIL missing scheduler.

**Step 3: Minimal implementation**

```python
class CartesianScheduler:
    def __init__(self, planner: DfaasPlanBuilder) -> None:
        self._planner = planner

    def propose_batch(self, *, ctx: DfaasRunContext, desired_size: int) -> list[list[tuple[str, int]]]:
        out: list[list[tuple[str, int]]] = []
        for cfg in ctx.configs:
            if len(out) >= desired_size:
                break
            key = config_key(cfg)
            if key in ctx.existing_index:
                continue
            out.append(cfg)
        return out
```

**Step 4: Run tests to green**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_peva_faas_scheduler.py tests/unit/lb_plugins/peva_faas/test_peva_faas_generator.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add lb_plugins/plugins/peva_faas/services/cartesian_scheduler.py lb_plugins/plugins/peva_faas/services/plan_builder.py tests/unit/lb_plugins/peva_faas/test_peva_faas_scheduler.py tests/unit/lb_plugins/peva_faas/test_peva_faas_generator.py
git commit -m "refactor(peva_faas): extract cartesian scheduler strategy"
```

### Task 4: Add DuckDB Core Store (Strict Schema)

**Files:**
- Modify: `pyproject.toml`
- Create: `lb_plugins/plugins/peva_faas/services/memory_store.py`
- Create: `tests/unit/lb_plugins/peva_faas/test_peva_faas_memory_store.py`

**Step 1: Write failing tests**

```python
def test_store_bootstrap_creates_schema_meta(tmp_path: Path) -> None:
    store = DuckDBMemoryStore(tmp_path / "mem.duckdb", schema_version="peva_faas_mem_v1")
    store.startup()
    assert store.schema_version() == "peva_faas_mem_v1"


def test_store_rejects_schema_mismatch(tmp_path: Path) -> None:
    store = DuckDBMemoryStore(tmp_path / "mem.duckdb", schema_version="bad")
    with pytest.raises(ValueError, match="schema_version"):
        store.validate_preload_schema("peva_faas_mem_v1")
```

**Step 2: Run failing tests**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_peva_faas_memory_store.py -q`
Expected: FAIL missing dependency/store.

**Step 3: Minimal implementation**

- Add deps:
  - `duckdb>=1.1.0`
  - `pyarrow>=17.0.0`
- Implement tables:
  - `memory_schema_meta`
  - `run_sessions`
  - `config_catalog`
  - `execution_events`
  - `k6_raw_summaries`
  - `policy_updates`
- Implement unique key on `execution_events` by `(config_id, iteration, repetition, run_id)`.

**Step 4: Run tests to green**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_peva_faas_memory_store.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add pyproject.toml lb_plugins/plugins/peva_faas/services/memory_store.py tests/unit/lb_plugins/peva_faas/test_peva_faas_memory_store.py
git commit -m "feat(peva_faas): add duckdb strict memory schema"
```

### Task 5: Add Parquet Checkpointing (Core Preload Only)

**Files:**
- Create: `lb_plugins/plugins/peva_faas/services/memory_checkpoint.py`
- Test: `tests/unit/lb_plugins/peva_faas/test_peva_faas_memory_checkpoint.py`

**Step 1: Write failing tests**

```python
def test_preload_imports_only_core_tables(tmp_path: Path) -> None:
    ckpt = ParquetCheckpoint(...)
    ckpt.preload_core()
    assert "execution_events" in loaded_tables
    assert "k6_raw_summaries" not in loaded_tables


def test_export_writes_core_and_debug_separately(tmp_path: Path) -> None:
    ckpt.export_all()
    assert (tmp_path / "core" / "execution_events.parquet").exists()
    assert (tmp_path / "debug" / "k6_raw_summaries.parquet").exists()
```

**Step 2: Run tests to fail**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_peva_faas_memory_checkpoint.py -q`
Expected: FAIL.

**Step 3: Minimal implementation**

```python
class ParquetCheckpoint:
    CORE_TABLES = ("memory_schema_meta", "run_sessions", "config_catalog", "execution_events", "policy_updates")
    DEBUG_TABLES = ("k6_raw_summaries",)
```

- `preload_core()` imports only `CORE_TABLES`.
- `export_core()` and `export_debug()` write separate directories.

**Step 4: Run tests to green**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_peva_faas_memory_checkpoint.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add lb_plugins/plugins/peva_faas/services/memory_checkpoint.py tests/unit/lb_plugins/peva_faas/test_peva_faas_memory_checkpoint.py
git commit -m "feat(peva_faas): add core/debug parquet checkpoint split"
```

### Task 6: Add Tensor Cache + Memory Engine

**Files:**
- Create: `lb_plugins/plugins/peva_faas/services/tensor_cache.py`
- Create: `lb_plugins/plugins/peva_faas/services/memory_engine.py`
- Test: `tests/unit/lb_plugins/peva_faas/test_peva_faas_memory_engine.py`

**Step 1: Write failing tests**

```python
def test_ingest_updates_store_and_hot_cache() -> None:
    engine.ingest_event(event)
    assert engine.is_seen(event.key)
    assert engine.tensor_cache_size() == 1


def test_online_mode_triggers_policy_update_per_event() -> None:
    engine.ingest_event(event)
    policy.update_online.assert_called_once()


def test_micro_batch_mode_triggers_policy_update_by_threshold() -> None:
    engine.ingest_event(e1)
    engine.ingest_event(e2)
    policy.update_batch.assert_called_once()
```

**Step 2: Run failing tests**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_peva_faas_memory_engine.py -q`
Expected: FAIL.

**Step 3: Minimal implementation**

- `TensorCache` stores numeric features + labels keyed by unique event key.
- `InProcessMemoryEngine` composes store + checkpoint + cache + policy.
- Respect mode semantics:
  - `online`: immediate `update_online(event)`
  - `micro_batch`: accumulate until `N` (and optionally `T`)

**Step 4: Run tests to green**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_peva_faas_memory_engine.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add lb_plugins/plugins/peva_faas/services/tensor_cache.py lb_plugins/plugins/peva_faas/services/memory_engine.py tests/unit/lb_plugins/peva_faas/test_peva_faas_memory_engine.py
git commit -m "feat(peva_faas): add in-process memory engine with online/micro-batch"
```

### Task 7: Refactor Run Loop To Use Scheduler + Memory Engine

**Files:**
- Modify: `lb_plugins/plugins/peva_faas/services/run_execution.py`
- Modify: `lb_plugins/plugins/peva_faas/generator.py`
- Modify: `lb_plugins/plugins/peva_faas/services/__init__.py`
- Test: `tests/unit/lb_plugins/peva_faas/test_peva_faas_run_execution.py`

**Step 1: Write failing tests**

```python
def test_executor_requests_sequential_batch_from_scheduler() -> None:
    executor.execute(ctx)
    scheduler.propose_batch.assert_called()


def test_seen_config_is_skipped_without_replacement() -> None:
    # desired batch=3, one seen => execute <=2
    executor.execute(ctx)
    assert executed_count == 2
```

**Step 2: Run failing tests**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_peva_faas_run_execution.py -q`
Expected: FAIL due to old direct-loop logic.

**Step 3: Minimal implementation**

- Keep sequential execution.
- Use scheduler to get next batch.
- For each executed event:
  - append current artifacts (existing behavior)
  - call `memory_engine.ingest_event(...)`
- preserve skip semantics and overload handling.

**Step 4: Run tests to green**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_peva_faas_run_execution.py tests/unit/lb_plugins/peva_faas/test_peva_faas_generator.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add lb_plugins/plugins/peva_faas/services/run_execution.py lb_plugins/plugins/peva_faas/generator.py lb_plugins/plugins/peva_faas/services/__init__.py tests/unit/lb_plugins/peva_faas/test_peva_faas_run_execution.py tests/unit/lb_plugins/peva_faas/test_peva_faas_generator.py
git commit -m "refactor(peva_faas): route execution through scheduler and memory engine"
```

### Task 8: Add Generic Algorithm Extension Hook

**Files:**
- Create: `lb_plugins/plugins/peva_faas/services/algorithm_loader.py`
- Test: `tests/unit/lb_plugins/peva_faas/test_peva_faas_algorithm_loader.py`
- Modify: `lb_plugins/plugins/peva_faas/generator.py`

**Step 1: Write failing tests**

```python
def test_default_algorithm_is_noop_policy() -> None:
    policy = load_policy_algorithm(None)
    assert policy.__class__.__name__ == "NoOpPolicy"


def test_custom_entrypoint_loads_algorithm() -> None:
    policy = load_policy_algorithm("tests.fixtures.custom_algo:CustomPolicy")
    assert policy.__class__.__name__ == "CustomPolicy"
```

**Step 2: Run tests to fail**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_peva_faas_algorithm_loader.py -q`
Expected: FAIL.

**Step 3: Minimal implementation**

```python
def load_policy_algorithm(entrypoint: str | None) -> PolicyAlgorithm:
    if not entrypoint:
        return NoOpPolicy()
    module_name, class_name = entrypoint.split(":", 1)
    mod = import_module(module_name)
    cls = getattr(mod, class_name)
    return cls()
```

- Validate contract conformance and clear error messages.

**Step 4: Run tests to green**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_peva_faas_algorithm_loader.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add lb_plugins/plugins/peva_faas/services/algorithm_loader.py lb_plugins/plugins/peva_faas/generator.py tests/unit/lb_plugins/peva_faas/test_peva_faas_algorithm_loader.py
git commit -m "feat(peva_faas): add custom policy algorithm entrypoint loader"
```

### Task 9: Docs, Compatibility, And Full Verification

**Files:**
- Modify: `lb_plugins/plugins/peva_faas/README.md`
- Modify: `tests/unit/lb_plugins/peva_faas/test_peva_faas_docs.py`

**Step 1: Write failing docs tests**

```python
def test_readme_documents_memory_core_and_debug_archive_split() -> None:
    assert "Memory Core" in readme
    assert "Debug Archive" in readme


def test_readme_documents_online_and_micro_batch_modes() -> None:
    assert "online" in readme
    assert "micro_batch" in readme
```

**Step 2: Run docs tests to fail**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_peva_faas_docs.py -q`
Expected: FAIL until README is updated.

**Step 3: Update docs minimally**

Document:
- new config keys
- strict schema policy
- preload/export behavior
- extension hook (`algorithm_entrypoint`)
- migration note: default behavior stays cartesian/sequential.

**Step 4: Run full relevant test set**

Run:
`uv run pytest tests/unit/lb_plugins/peva_faas/test_peva_faas_config.py tests/unit/lb_plugins/peva_faas/test_peva_faas_scheduler.py tests/unit/lb_plugins/peva_faas/test_peva_faas_memory_store.py tests/unit/lb_plugins/peva_faas/test_peva_faas_memory_checkpoint.py tests/unit/lb_plugins/peva_faas/test_peva_faas_memory_engine.py tests/unit/lb_plugins/peva_faas/test_peva_faas_algorithm_loader.py tests/unit/lb_plugins/peva_faas/test_peva_faas_run_execution.py tests/unit/lb_plugins/peva_faas/test_peva_faas_docs.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add lb_plugins/plugins/peva_faas/README.md tests/unit/lb_plugins/peva_faas/test_peva_faas_docs.py
git commit -m "docs(peva_faas): document memory architecture and extension model"
```

## Non-Goals (YAGNI v1)

- External policy service (gRPC/HTTP).
- Parallel batch execution.
- Auto schema migrations between versions.
- Preload of raw debug summaries.

## Risk Controls

- Keep `DfaasPlanBuilder` APIs stable to avoid broad regression.
- Gate new path behind defaults that mimic current behavior.
- Add focused unit tests for contract boundaries to avoid tight coupling.

## Rollout Strategy

1. Merge contracts/config/store first.
2. Merge scheduler/memory engine.
3. Switch executor integration.
4. Enable custom algorithm entrypoint.
5. Final docs and verification.

