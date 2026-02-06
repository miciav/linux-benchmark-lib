# PEVA-FAAS Multipass Stop + DuckDB E2E Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a PEVA-FAAS end-to-end Multipass test that provisions two VMs, verifies setup, runs at least one 1-minute configuration for one function, validates Prometheus metric collection, persists memory data in DuckDB, and verifies stop-file interruption with DB artifact transferred to controller output.

**Architecture:** Reuse the existing Multipass E2E scaffolding in `tests/e2e/test_dfaas_multipass_e2e.py`, then add missing runtime guarantees: (1) PEVA-FAAS must checkpoint/save memory state on interruption, and (2) collect phase must fetch DuckDB memory file from runner host to controller. Keep runtime changes minimal and plugin-scoped. Validate with unit tests first, then the new E2E scenario.

**Tech Stack:** Python 3.12+, pytest, Multipass, Ansible playbooks, BenchmarkController API, StopToken, PEVA-FAAS plugin (k6/OpenFaaS/Prometheus/DuckDB).

### Task 1: Add Unit Contract For Collecting PEVA-FAAS DuckDB Artifact

**Files:**
- Modify: `tests/unit/lb_plugins/peva_faas/test_peva_faas_playbooks.py`
- Modify: `lb_plugins/plugins/peva_faas/ansible/collect/post.yml`

**Step 1: Write the failing test**

Add a new test that loads `collect/post.yml` and asserts all of the following are present:
- task deriving `peva_faas_memory_db_path` from `benchmark_config.plugin_settings.peva_faas.memory.db_path` with default fallback,
- task normalizing relative DB path under `lb_workdir`,
- `ansible.builtin.stat` check for DB file,
- `ansible.builtin.fetch` task copying DuckDB to controller output.

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_peva_faas_playbooks.py -q`
Expected: FAIL (new tasks are missing).

**Step 3: Write minimal implementation**

In `collect/post.yml`, append tasks that:
- derive path from plugin settings (`memory.db_path`) with default `benchmark_results/peva_faas/memory/peva_faas.duckdb`,
- convert to absolute path if relative (`{{ lb_workdir }}/...`),
- `stat` the resolved path,
- `fetch` to `{{ output_root }}/memory/{{ inventory_hostname }}/` when present.

**Step 4: Run test to verify pass**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_peva_faas_playbooks.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add lb_plugins/plugins/peva_faas/ansible/collect/post.yml tests/unit/lb_plugins/peva_faas/test_peva_faas_playbooks.py
git commit -m "feat(peva_faas): collect duckdb memory artifact during plugin post-collect"
```

### Task 2: Make PEVA-FAAS Generator Stop Path Persist Memory Checkpoint

**Files:**
- Modify: `lb_plugins/plugins/peva_faas/generator.py`
- Modify: `lb_plugins/plugins/peva_faas/services/k6_runner.py`
- Modify: `tests/unit/lb_plugins/peva_faas/test_peva_faas_generator.py`

**Step 1: Write the failing tests**

Add tests for:
1. `DfaasGenerator._stop_workload()` requests k6 stop/termination.
2. On interruption/error path, memory checkpoint is invoked exactly once before exit.

Use monkeypatch/mocks for `K6Runner` and memory engine objects; assert behavior, not internals.

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_peva_faas_generator.py -q`
Expected: FAIL (`_stop_workload` no-op and no guaranteed checkpoint call).

**Step 3: Write minimal implementation**

- In `k6_runner.py`: add minimal stop hook (`stop_current_run()` or equivalent) that terminates active `k6` subprocess if alive.
- In `generator.py`:
  - implement `_stop_workload()` to call k6 stop hook,
  - ensure `_memory_engine.checkpoint()` runs in a `finally` block around execution path so interruption still persists DB-backed state.

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_peva_faas_generator.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add lb_plugins/plugins/peva_faas/generator.py lb_plugins/plugins/peva_faas/services/k6_runner.py tests/unit/lb_plugins/peva_faas/test_peva_faas_generator.py
git commit -m "feat(peva_faas): persist memory checkpoint and stop active k6 run on interruption"
```

### Task 3: Add Unit Guard For Collect Path Resolution Safety

**Files:**
- Modify: `tests/unit/lb_plugins/peva_faas/test_peva_faas_playbooks.py`
- Modify: `lb_plugins/plugins/peva_faas/ansible/collect/post.yml`

**Step 1: Write the failing test**

Add assertions that collection logic only resolves either:
- absolute configured path, or
- `{{ lb_workdir }}/<relative-path>`
and does not use uncontrolled shell expansion.

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_peva_faas_playbooks.py -q`
Expected: FAIL until path normalization is explicit.

**Step 3: Write minimal implementation**

Use `set_fact` with deterministic Jinja transforms for absolute/relative handling and avoid shell.

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_peva_faas_playbooks.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add lb_plugins/plugins/peva_faas/ansible/collect/post.yml tests/unit/lb_plugins/peva_faas/test_peva_faas_playbooks.py
git commit -m "test(peva_faas): guard deterministic duckdb collect path resolution"
```

### Task 4: Add New E2E Test For PEVA-FAAS Stop + DuckDB Transfer

**Files:**
- Modify: `tests/e2e/test_dfaas_multipass_e2e.py`

**Step 1: Write the failing E2E test skeleton**

Add `test_peva_faas_multipass_stopfile_duckdb_e2e(...)` with explicit assertions for:
- two VM roles (k3s + runner),
- setup verification (`kubectl` resources on k3s, `k6 version` on runner),
- config with one function and `duration="1m"`,
- stop request issued via stop file mechanism,
- DuckDB file exists in controller output after collect.

Start with minimal implementation that intentionally fails on not-yet-implemented stop/DB-transfer checks.

**Step 2: Run test to verify it fails**

Run:
`LB_RUN_PEVA_FAAS_MULTIPASS_E2E=1 LB_MULTIPASS_VM_COUNT=2 uv run pytest tests/e2e/test_dfaas_multipass_e2e.py::test_peva_faas_multipass_stopfile_duckdb_e2e -q -s`
Expected: FAIL on missing interruption/data-transfer guarantees.

**Step 3: Implement minimal E2E flow**

In the new test:
- reuse `multipass_two_vms` fixture and helper functions already in file,
- run `setup_target.yml` on k3s VM and `setup_k6.yml` on runner VM,
- build `BenchmarkConfig` with PEVA-FAAS one-function/1-minute config,
- run controller in background thread with `ControllerOptions(stop_token=StopToken(stop_file=<local-stop-file>))`,
- wait for first running signal/LB_EVENT, then create stop file,
- wait completion and assert controller exits (not hung),
- verify Prometheus query pre-checks were successful,
- verify output includes PEVA-FAAS metrics/result artifacts,
- verify DuckDB file fetched to controller output tree.

**Step 4: Run test to verify pass**

Run:
`LB_RUN_PEVA_FAAS_MULTIPASS_E2E=1 LB_MULTIPASS_VM_COUNT=2 uv run pytest tests/e2e/test_dfaas_multipass_e2e.py::test_peva_faas_multipass_stopfile_duckdb_e2e -q -s`
Expected: PASS.

**Step 5: Commit**

```bash
git add tests/e2e/test_dfaas_multipass_e2e.py
git commit -m "test(e2e): verify peva_faas multipass interruption and duckdb artifact transfer"
```

### Task 5: Add E2E Assertions For Prometheus-Backed Data And DuckDB Content

**Files:**
- Modify: `tests/e2e/test_dfaas_multipass_e2e.py`

**Step 1: Write the failing assertions**

Extend the same E2E test with checks that:
- Prometheus-driven PEVA metrics files are non-empty,
- fetched DuckDB file can be opened with `duckdb.connect(...)`,
- at least one expected table exists and has rows (`execution_events` or schema-equivalent table expected by plugin memory store).

**Step 2: Run test to verify it fails (if schema/path assumptions are wrong)**

Run same targeted E2E command.
Expected: FAIL until table/path checks align with actual generated DB.

**Step 3: Write minimal implementation adjustments**

Adjust assertion helpers in test to align with real PEVA schema/table names produced by `DuckDBMemoryStore`.

**Step 4: Run test to verify pass**

Run same targeted E2E command.
Expected: PASS.

**Step 5: Commit**

```bash
git add tests/e2e/test_dfaas_multipass_e2e.py
git commit -m "test(e2e): assert prometheus-derived metrics and duckdb persistence"
```

### Task 6: Full Verification Gate

**Files:**
- No new files (verification only)

**Step 1: Run targeted unit suites**

Run:
```bash
uv run pytest \
  tests/unit/lb_plugins/peva_faas/test_peva_faas_generator.py \
  tests/unit/lb_plugins/peva_faas/test_peva_faas_playbooks.py -q
```
Expected: PASS.

**Step 2: Run targeted E2E scenario**

Run:
```bash
LB_RUN_PEVA_FAAS_MULTIPASS_E2E=1 LB_MULTIPASS_VM_COUNT=2 \
uv run pytest tests/e2e/test_dfaas_multipass_e2e.py::test_peva_faas_multipass_stopfile_duckdb_e2e -q -s
```
Expected: PASS.

**Step 3: Run lint/type checks for touched modules**

Run:
```bash
env UV_CACHE_DIR=.uv-cache uv run ruff check \
  lb_plugins/plugins/peva_faas \
  tests/unit/lb_plugins/peva_faas \
  tests/e2e/test_dfaas_multipass_e2e.py

env UV_CACHE_DIR=.uv-cache uv run mypy lb_plugins/plugins/peva_faas
```
Expected: PASS or pre-existing failures only.

### Rollout Notes

- The E2E test should stay gated behind existing Multipass env controls and markers (`inter_e2e`, `inter_multipass`, `slowest`).
- Keep VM setup assertions explicit so failures identify which host role broke (runner vs k3s).
- Keep stop/duckdb assertions deterministic by using known output subpaths under test `tmp_path`.
