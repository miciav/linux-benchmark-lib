# Bug Remediation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** eliminare i bug funzionali, i colli di bottiglia caldi e le duplicazioni che oggi rendono stop, resume, provisioning, FaaS logging e discovery dei run fragili o incoerenti.

**Architecture:** affrontare prima i bug che alterano il comportamento osservabile o lasciano stato sporco, poi convergere i punti di integrazione duplicati (`resume`, journal, FaaS log manager, plan builder) verso helper condivisi. Ogni fix deve partire da un test rosso mirato, chiudere il minimo codice necessario e solo dopo affrontare il refactor associato.

**Tech Stack:** Python 3.13, pytest, Typer, PySide6, Fabric/Invoke, Ansible callback plugins, Multipass, Docker/Podman.

---

## Execution Order

1. Bloccare i bug di stop/journal/k6 che falsano l’esecuzione.
2. Sistemare deadlock GUI, coupling sul root logger e rollback del provisioning.
3. Allineare catalogo run, resume, collector di system info e aggregazione.
4. Spegnere il debug event tracing di default.
5. Ridurre la duplicazione FaaS e il costo combinatorio di startup.

### Task 1: Stop Propagation And Responsive Sleep Paths

**Files:**
- Modify: `lb_runner/engine/executor.py`
- Modify: `lb_runner/engine/execution.py`
- Modify: `lb_runner/engine/runner.py`
- Test: `tests/unit/lb_runner/engine_tests/test_executor.py`
- Create: `tests/unit/lb_runner/engine_tests/test_stop_responsiveness.py`

**Step 1: Write the failing tests**

Add a test in `tests/unit/lb_runner/engine_tests/test_executor.py` that proves `wait_for_generator()` receives `context.stop_token`.

```python
def test_execute_passes_stop_token_to_wait_loop(executor, context):
    context.stop_token = MagicMock()
    generator = MagicMock()
    metric_session = MagicMock()
    metric_session.collectors = []
    context.metric_manager.begin_repetition.return_value = metric_session

    with patch("lb_runner.engine.executor.resolve_duration", return_value=1):
        with patch("lb_runner.engine.executor.wait_for_generator") as wait_mock:
            wait_mock.return_value = datetime.now()
            executor.execute("test_workload", generator, 1, 1)

    assert wait_mock.call_args.kwargs["stop_token"] is context.stop_token
```

Add a new test file `tests/unit/lb_runner/engine_tests/test_stop_responsiveness.py` that patches `time.sleep` and verifies warmup/cooldown loops re-check the stop token between short sleep slices instead of blocking for the full duration.

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/lb_runner/engine_tests/test_executor.py tests/unit/lb_runner/engine_tests/test_stop_responsiveness.py -q`

Expected: FAIL because `stop_token` is not forwarded and the current sleep path is monolithic.

**Step 3: Write minimal implementation**

- Pass `self.context.stop_token` into `wait_for_generator(...)` inside `RepetitionExecutor.execute()`.
- Replace long `time.sleep(...)` warmup/cooldown waits with a helper like `_sleep_with_stop_checks(total_seconds, stop_token, quantum=0.1)` in `lb_runner/engine/execution.py`.
- Reuse the helper from `lb_runner/engine/runner.py` before each repetition.

```python
test_end_time = wait_for_generator(
    generator,
    duration,
    test_name,
    repetition,
    logger=logger,
    stop_token=self.context.stop_token,
)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/lb_runner/engine_tests/test_executor.py tests/unit/lb_runner/engine_tests/test_stop_responsiveness.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add tests/unit/lb_runner/engine_tests/test_executor.py tests/unit/lb_runner/engine_tests/test_stop_responsiveness.py lb_runner/engine/executor.py lb_runner/engine/execution.py lb_runner/engine/runner.py
git commit -m "fix: propagate stop token through runner waits"
```

### Task 2: Journal Terminal States And Save Batching

**Files:**
- Modify: `lb_controller/services/journal.py`
- Modify: `lb_controller/services/journal_sync.py`
- Test: `tests/unit/lb_controller/test_controller_stop.py`
- Modify: `tests/unit/lb_controller/test_journal_sync.py`

**Step 1: Write the failing tests**

Extend `tests/unit/lb_controller/test_controller_stop.py` with a case that emits a `stopped` event and asserts the journal entry is terminal, not `RUNNING`.

Extend `tests/unit/lb_controller/test_journal_sync.py` with a test that patches `journal.save` and verifies `update_all_reps()` persists once per workload, not once per repetition.

```python
def test_update_all_reps_saves_once(tmp_path):
    journal, cfg = _journal_for()
    journal.save = MagicMock()
    update_all_reps(
        repetitions=3,
        journal=journal,
        journal_path=tmp_path / "journal.json",
        hosts=cfg.remote_hosts,
        workload="stress_ng",
        status=RunStatus.SKIPPED,
    )
    journal.save.assert_called_once()
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/lb_controller/test_controller_stop.py tests/unit/lb_controller/test_journal_sync.py -q`

Expected: FAIL because `stopped` falls back to `RUNNING` and `update_all_reps()` saves repeatedly.

**Step 3: Write minimal implementation**

- Expand `status_map` in `LogSink._update_journal()` to cover `stopped`, `cancelled`, and `unreachable`.
- Decide one canonical mapping:
  - `stopped` -> `RunStatus.SKIPPED` or a new explicit terminal status if the model supports it.
  - `cancelled` -> same terminal mapping.
  - `unreachable` -> `RunStatus.FAILED`.
- Refactor `update_journal_tasks()` and `update_all_reps()` so bulk updates mutate all tasks first, then save/refresh once.

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/lb_controller/test_controller_stop.py tests/unit/lb_controller/test_journal_sync.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add tests/unit/lb_controller/test_controller_stop.py tests/unit/lb_controller/test_journal_sync.py lb_controller/services/journal.py lb_controller/services/journal_sync.py
git commit -m "fix: normalize terminal journal states and batch saves"
```

### Task 3: Harden Remote K6 Execution

**Files:**
- Modify: `lb_plugins/plugins/dfaas/services/k6_runner.py`
- Modify: `tests/unit/lb_plugins/dfaas/test_dfaas_k6_runner_fabric.py`

**Step 1: Write the failing tests**

Add one test that expects the remote command to run under `bash -lc` with `set -o pipefail`.

Add one test that exercises a `target_name` containing a space and asserts `mkdir`/`tee` paths are shell-quoted.

```python
def test_execute_uses_pipefail_and_quotes_workspace(mock_conn_cls, k6_runner):
    ...
    expected = "bash -lc 'set -o pipefail; k6 run ... | tee ...'"
    mock_conn.run.assert_any_call(expected, hide=True, out_stream=ANY, warn=True, in_stream=False)
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/lb_plugins/dfaas/test_dfaas_k6_runner_fabric.py -q`

Expected: FAIL because the command is currently `k6 ... | tee ...` without `pipefail` and without robust quoting for `workspace`/`log_path`.

**Step 3: Write minimal implementation**

- Extract a helper that shell-quotes `workspace`, `script_path`, `summary_path`, and `log_path`.
- Build the remote execution command as:

```python
return "bash -lc " + shlex.quote(
    f"set -o pipefail; {k6_cmd} 2>&1 | tee {shlex.quote(log_path)}"
)
```

- Reuse the helper from both the main `execute()` path and the refactored helpers already present later in the file.

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/lb_plugins/dfaas/test_dfaas_k6_runner_fabric.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add tests/unit/lb_plugins/dfaas/test_dfaas_k6_runner_fabric.py lb_plugins/plugins/dfaas/services/k6_runner.py
git commit -m "fix: preserve k6 failures in remote fabric pipeline"
```

### Task 4: Fix GUI Worker Deadlock And Root Logger Coupling

**Files:**
- Modify: `lb_gui/workers/run_worker.py`
- Test: `tests/unit/lb_gui/test_run_worker.py`
- Modify: `lb_plugins/plugins/peva_faas/services/log_manager.py`
- Modify: `lb_plugins/plugins/dfaas/services/log_manager.py`
- Modify: `tests/unit/lb_plugins/peva_faas/test_peva_faas_log_manager.py`
- Create: `tests/unit/lb_plugins/dfaas/test_dfaas_log_manager.py`

**Step 1: Write the failing tests**

Add a lifecycle test in `tests/unit/lb_gui/test_run_worker.py` that patches `QThread.currentThread()` and proves `_cleanup_thread()` does not call `wait()` when already running inside the owned thread.

Extend `tests/unit/lb_plugins/peva_faas/test_peva_faas_log_manager.py` with a case where a foreign `LBEventLogHandler` is attached to root and the manager must still emit its own event if the run metadata does not match.

Create `tests/unit/lb_plugins/dfaas/test_dfaas_log_manager.py` with the same scenario to keep both plugin variants aligned.

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/lb_gui/test_run_worker.py tests/unit/lb_plugins/peva_faas/test_peva_faas_log_manager.py tests/unit/lb_plugins/dfaas/test_dfaas_log_manager.py -q`

Expected: FAIL because `RunWorker` self-joins and the log manager suppresses events based on root-global state instead of run-local identity.

**Step 3: Write minimal implementation**

- Guard `_cleanup_thread()` the same way as the other workers:

```python
if self._thread is not None:
    self._thread.quit()
    if QThread.currentThread() is not self._thread:
        self._thread.wait()
```

- Replace “any `LBEventLogHandler` on root” checks with a precise predicate that only suppresses fallback logging when the existing handler belongs to the same `(run_id, host, workload, repetition)`.

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/lb_gui/test_run_worker.py tests/unit/lb_plugins/peva_faas/test_peva_faas_log_manager.py tests/unit/lb_plugins/dfaas/test_dfaas_log_manager.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add tests/unit/lb_gui/test_run_worker.py tests/unit/lb_plugins/peva_faas/test_peva_faas_log_manager.py tests/unit/lb_plugins/dfaas/test_dfaas_log_manager.py lb_gui/workers/run_worker.py lb_plugins/plugins/peva_faas/services/log_manager.py lb_plugins/plugins/dfaas/services/log_manager.py
git commit -m "fix: unblock gui worker teardown and scope lb event handlers"
```

### Task 5: Run Catalog Correctness And Resume De-duplication

**Files:**
- Modify: `lb_controller/services/run_catalog_service.py`
- Modify: `lb_ui/cli/commands/resume.py`
- Modify: `tests/unit/lb_controller/test_run_catalog_service.py`
- Create: `tests/unit/lb_ui/test_cli_resume_catalog.py`

**Step 1: Write the failing tests**

Add a `RunCatalogService` test that asserts `report_root` and `data_export_root` are `None` when directories do not exist.

Create `tests/unit/lb_ui/test_cli_resume_catalog.py` that patches `RunCatalogService.list_runs()` and proves `resume` uses the service instead of re-parsing the journal tree directly.

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/lb_controller/test_run_catalog_service.py tests/unit/lb_ui/test_cli_resume_catalog.py -q`

Expected: FAIL because `_existing_or_none()` currently returns missing paths and `resume.py` implements a separate filesystem scanner.

**Step 3: Write minimal implementation**

- Fix `_existing_or_none()` to return `None` when the directory is absent.
- Introduce a small adapter/helper inside `resume.py` that delegates discovery and metadata loading to `RunCatalogService`.
- Delete the duplicated local helpers only after the CLI tests are green.

```python
@staticmethod
def _existing_or_none(root: Optional[Path]) -> Optional[Path]:
    return root if root and root.exists() else None
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/lb_controller/test_run_catalog_service.py tests/unit/lb_ui/test_cli_resume_catalog.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add tests/unit/lb_controller/test_run_catalog_service.py tests/unit/lb_ui/test_cli_resume_catalog.py lb_controller/services/run_catalog_service.py lb_ui/cli/commands/resume.py
git commit -m "fix: reuse run catalog for resume discovery"
```

### Task 6: System Info And Aggregation Robustness

**Files:**
- Modify: `lb_runner/services/system_info_collectors.py`
- Modify: `lb_runner/metric_collectors/aggregators.py`
- Modify: `tests/unit/lb_runner/services_tests/test_system_info.py`
- Create: `tests/unit/lb_runner/services_tests/test_aggregators.py`

**Step 1: Write the failing tests**

Extend `tests/unit/lb_runner/services_tests/test_system_info.py` with:
- a case where `lsblk -J -O` returns human-readable `size` plus `bytes`, and the collector must preserve `size_bytes`;
- a case where `psutil.net_if_addrs()` returns a MAC address and `_collect_nics()` must populate it.

Create `tests/unit/lb_runner/services_tests/test_aggregators.py` with partial DataFrames that include `disk_read_bytes` but not `disk_write_bytes`, and `net_bytes_sent` but not `net_bytes_recv`.

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/lb_runner/services_tests/test_system_info.py tests/unit/lb_runner/services_tests/test_aggregators.py -q`

Expected: FAIL because disk sizes are dropped, MAC detection is wrong, and the aggregator assumes paired columns always exist.

**Step 3: Write minimal implementation**

- Prefer `lsblk -J -b -O` or consume the `bytes` field before falling back to `size`.
- Compare socket families correctly (`psutil.AF_LINK` or `socket.AF_PACKET` depending on platform).
- Guard disk/network throughput calculations with both required columns present.

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/lb_runner/services_tests/test_system_info.py tests/unit/lb_runner/services_tests/test_aggregators.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add tests/unit/lb_runner/services_tests/test_system_info.py tests/unit/lb_runner/services_tests/test_aggregators.py lb_runner/services/system_info_collectors.py lb_runner/metric_collectors/aggregators.py
git commit -m "fix: preserve system info fields and tolerate partial metrics"
```

### Task 7: Provisioner Rollback On Partial Failure

**Files:**
- Modify: `lb_provisioner/providers/docker.py`
- Modify: `lb_provisioner/providers/multipass.py`
- Modify: `tests/unit/lb_provisioner/test_multipass_lifecycle.py`
- Create: `tests/unit/lb_provisioner/test_docker_provisioner.py`

**Step 1: Write the failing tests**

Add a Multipass test that forces failure on the second VM and asserts the first VM is destroyed and its keys are removed.

Create `tests/unit/lb_provisioner/test_docker_provisioner.py` with the analogous container case.

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/lb_provisioner/test_multipass_lifecycle.py tests/unit/lb_provisioner/test_docker_provisioner.py -q`

Expected: FAIL because `provision()` currently returns only on total success and performs no rollback for already-created nodes.

**Step 3: Write minimal implementation**

- Accumulate destroy callbacks as soon as a node becomes externally visible.
- Wrap the provisioning loop in `try/except`; on failure, destroy all previously-created nodes in reverse order and re-raise a `ProvisioningError` with the original cause.

```python
created: list[ProvisionedNode] = []
try:
    ...
    created.append(node)
except Exception:
    for node in reversed(created):
        node.destroy()
    raise
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/lb_provisioner/test_multipass_lifecycle.py tests/unit/lb_provisioner/test_docker_provisioner.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add tests/unit/lb_provisioner/test_multipass_lifecycle.py tests/unit/lb_provisioner/test_docker_provisioner.py lb_provisioner/providers/docker.py lb_provisioner/providers/multipass.py
git commit -m "fix: rollback partially provisioned nodes on failure"
```

### Task 8: Editor Parsing And Event Debug Defaults

**Files:**
- Modify: `lb_app/services/config_service.py`
- Modify: `lb_app/services/run_events.py`
- Modify: `lb_controller/ansible/callback_plugins/lb_events.py`
- Create: `tests/unit/lb_app/test_config_service_editor.py`
- Create: `tests/unit/lb_app/test_run_events_debug.py`
- Create: `tests/unit/lb_controller/ansible_tests/test_lb_events_debug.py`

**Step 1: Write the failing tests**

Create `tests/unit/lb_app/test_config_service_editor.py` asserting that `EDITOR="code -w"` is split into `["code", "-w", "<path>"]`.

Create two debug tests asserting that `LB_EVENT_DEBUG` is disabled by default and only writes sidecar debug files when explicitly enabled.

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/lb_app/test_config_service_editor.py tests/unit/lb_app/test_run_events_debug.py tests/unit/lb_controller/ansible_tests/test_lb_events_debug.py -q`

Expected: FAIL because `subprocess.run([editor, path])` treats the full string as a binary name and both event debug paths default to `"1"`.

**Step 3: Write minimal implementation**

- Use `shlex.split(editor)` before appending the path.
- Change debug defaults to opt-in:

```python
_DEBUG = os.getenv("LB_EVENT_DEBUG", "0").lower() in ("1", "true", "yes")
```

- Keep debug file writes behind the same helper in both app and callback paths.

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/lb_app/test_config_service_editor.py tests/unit/lb_app/test_run_events_debug.py tests/unit/lb_controller/ansible_tests/test_lb_events_debug.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add tests/unit/lb_app/test_config_service_editor.py tests/unit/lb_app/test_run_events_debug.py tests/unit/lb_controller/ansible_tests/test_lb_events_debug.py lb_app/services/config_service.py lb_app/services/run_events.py lb_controller/ansible/callback_plugins/lb_events.py
git commit -m "fix: make editor parsing robust and disable event debug by default"
```

### Task 9: Reduce FaaS Drift And Startup Cost

**Files:**
- Create: `lb_plugins/plugins/_faas_shared/__init__.py`
- Create: `lb_plugins/plugins/_faas_shared/plan_builder.py`
- Create: `lb_plugins/plugins/_faas_shared/config_enumerator.py`
- Modify: `lb_plugins/plugins/dfaas/services/plan_builder.py`
- Modify: `lb_plugins/plugins/peva_faas/services/plan_builder.py`
- Modify: `lb_plugins/plugins/peva_faas/generator.py`
- Modify: `lb_plugins/plugins/peva_faas/services/run_execution.py`
- Test: `tests/unit/lb_plugins/dfaas/test_dfaas_generator.py`
- Test: `tests/unit/lb_plugins/peva_faas/test_peva_faas_generator.py`
- Test: `tests/unit/lb_plugins/peva_faas/test_peva_faas_run_execution.py`

**Step 1: Write the failing tests**

Add a regression test proving `expected_runtime_seconds` does not force materializing the full Cartesian space twice for the same config. Use a patched enumerator and assert a single pass or a bounded lazy pass.

Add parity tests that both plugin `plan_builder` modules delegate to the new shared helper and still return the same public shape.

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/lb_plugins/dfaas/test_dfaas_generator.py tests/unit/lb_plugins/peva_faas/test_peva_faas_generator.py tests/unit/lb_plugins/peva_faas/test_peva_faas_run_execution.py -q`

Expected: FAIL because both plugins own their own plan-building logic and `peva_faas` recomputes all configurations at least twice.

**Step 3: Write minimal implementation**

- Introduce a shared lazy enumerator API:

```python
def iter_config_pairs(... ) -> Iterator[list[tuple[str, int]]]:
    yield ...
```

- Make `expected_runtime_seconds` consume counts from the iterator without storing the full list.
- Point both `dfaas` and `peva_faas` `plan_builder.py` files at the shared implementation.

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/lb_plugins/dfaas/test_dfaas_generator.py tests/unit/lb_plugins/peva_faas/test_peva_faas_generator.py tests/unit/lb_plugins/peva_faas/test_peva_faas_run_execution.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add lb_plugins/plugins/_faas_shared/__init__.py lb_plugins/plugins/_faas_shared/plan_builder.py lb_plugins/plugins/_faas_shared/config_enumerator.py lb_plugins/plugins/dfaas/services/plan_builder.py lb_plugins/plugins/peva_faas/services/plan_builder.py lb_plugins/plugins/peva_faas/generator.py lb_plugins/plugins/peva_faas/services/run_execution.py tests/unit/lb_plugins/dfaas/test_dfaas_generator.py tests/unit/lb_plugins/peva_faas/test_peva_faas_generator.py tests/unit/lb_plugins/peva_faas/test_peva_faas_run_execution.py
git commit -m "refactor: share faas plan building and lazy enumeration"
```

### Task 10: Remove Known Dead Or Divergent Cleanup Paths

**Files:**
- Modify: `lb_runner/engine/execution.py`
- Modify: `lb_runner/engine/executor.py`
- Test: `tests/unit/lb_runner/engine_tests/test_executor.py`

**Step 1: Write the failing test**

Add one test asserting there is a single cleanup path responsible for stopping generator and collectors after an error, and that the exercised path is `RepetitionExecutor._cleanup_after_run()`.

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/lb_runner/engine_tests/test_executor.py -q`

Expected: FAIL once the test explicitly imports and checks the stale helper contract.

**Step 3: Write minimal implementation**

- Delete or inline the unused `cleanup_after_run()` helper from `lb_runner/engine/execution.py`.
- Keep the tested cleanup path in `lb_runner/engine/executor.py` as the single source of truth.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/lb_runner/engine_tests/test_executor.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add tests/unit/lb_runner/engine_tests/test_executor.py lb_runner/engine/execution.py lb_runner/engine/executor.py
git commit -m "refactor: remove duplicate runner cleanup path"
```

## Final Verification

Run the focused suites first:

```bash
uv run pytest \
  tests/unit/lb_runner/engine_tests/test_executor.py \
  tests/unit/lb_runner/engine_tests/test_stop_responsiveness.py \
  tests/unit/lb_controller/test_controller_stop.py \
  tests/unit/lb_controller/test_journal_sync.py \
  tests/unit/lb_plugins/dfaas/test_dfaas_k6_runner_fabric.py \
  tests/unit/lb_plugins/peva_faas/test_peva_faas_log_manager.py \
  tests/unit/lb_plugins/dfaas/test_dfaas_log_manager.py \
  tests/unit/lb_controller/test_run_catalog_service.py \
  tests/unit/lb_ui/test_cli_resume_catalog.py \
  tests/unit/lb_runner/services_tests/test_system_info.py \
  tests/unit/lb_runner/services_tests/test_aggregators.py \
  tests/unit/lb_provisioner/test_multipass_lifecycle.py \
  tests/unit/lb_provisioner/test_docker_provisioner.py \
  tests/unit/lb_app/test_config_service_editor.py \
  tests/unit/lb_app/test_run_events_debug.py \
  tests/unit/lb_controller/ansible_tests/test_lb_events_debug.py \
  tests/unit/lb_gui/test_run_worker.py -q
```

Then run the broader safety net:

```bash
uv run pytest tests/unit/lb_runner tests/unit/lb_controller tests/unit/lb_app tests/unit/lb_ui tests/unit/lb_gui tests/unit/lb_plugins tests/unit/lb_provisioner -q
```

If the broader suite passes, run the static checks most likely to regress during the refactor:

```bash
uv run flake8 --max-cognitive-complexity 15 --select CCR001 lb_runner lb_controller lb_app lb_ui lb_plugins
uv run mypy lb_runner lb_controller lb_app lb_ui lb_plugins lb_provisioner
```
