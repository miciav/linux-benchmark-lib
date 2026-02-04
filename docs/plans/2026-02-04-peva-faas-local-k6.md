# PEVA-faas Local K6 + K3s Target Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move PEVA-faas to run k6 locally on the runner/target host, manage the OpenFaaS/k3s node via new `k3s_*` fields, standardize plugin setup playbook naming, and allow per-workload collector disablement.

**Architecture:** The controller still prepares common assets via `lb_controller/ansible/playbooks/setup.yml`. Each plugin now exposes `ansible/setup_plugin.yml` for plugin-specific setup. For PEVA-faas, `setup_plugin.yml` installs k6 locally on the runner/target host and provisions the k3s/OpenFaaS node via Ansible using `k3s_*` config. The runner executes k6 locally; the generator points gateway/prometheus to the k3s host. Collector execution becomes per-workload via `WorkloadConfig.collectors_enabled`.

**Tech Stack:** Python 3.12/3.13, pytest, Ansible, Pydantic, k6 (local subprocess), Fabric removal for PEVA-faas.

### Task 1: Stabilize lb_gui Unit Tests When Submodule Missing

**Files:**
- Create: `tests/helpers/optional_imports.py`
- Create: `tests/unit/test_optional_imports.py`
- Modify: `tests/unit/lb_gui/conftest.py`

**Step 1: Write the failing test**

```python
from tests.helpers.optional_imports import module_available


def test_module_available_detects_existing_module() -> None:
    assert module_available("json") is True


def test_module_available_detects_missing_module() -> None:
    assert module_available("definitely_missing_module_123") is False
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_optional_imports.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'tests.helpers.optional_imports'`

**Step 3: Write minimal implementation**

```python
# tests/helpers/optional_imports.py
import importlib.util


def module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_optional_imports.py -q`
Expected: PASS

**Step 5: Wire lb_gui conftest to skip when lb_gui is missing**

```python
# tests/unit/lb_gui/conftest.py
from tests.helpers.optional_imports import module_available

HAS_PYSIDE6 = module_available("PySide6")
HAS_LB_GUI = module_available("lb_gui.viewmodels")

if not HAS_PYSIDE6 or not HAS_LB_GUI:
    collect_ignore = [
        "test_run_worker.py",
        "test_run_setup_vm.py",
        "test_dashboard_vm.py",
        "test_results_vm.py",
        "test_analytics_vm.py",
        "test_config_plugins_doctor_vm.py",
    ]
```

**Step 6: Run lb_gui tests to verify skip behavior**

Run: `uv run pytest tests/unit/lb_gui -q`
Expected: PASS with skips (if lb_gui submodule is not initialized).

**Step 7: Commit**

```bash
git add tests/helpers/optional_imports.py tests/unit/test_optional_imports.py tests/unit/lb_gui/conftest.py
git commit -m "test: skip lb_gui tests when submodule missing"
```

### Task 2: Standardize Plugin Setup Playbook Name to setup_plugin.yml

**Files:**
- Modify: `tests/unit/lb_controller/test_controller.py`
- Modify: `lb_plugins/plugins/*/plugin.py` (all plugins that reference `ansible/setup.yml`)
- Rename: `lb_plugins/plugins/*/ansible/setup.yml` → `setup_plugin.yml`
- Rename: `lb_plugins/plugins/phoronix_test_suite/ansible/setup.yml` → `setup_plugin.yml`

**Step 1: Update tests to expect setup_plugin.yml**

```python
# tests/unit/lb_controller/test_controller.py
if str(call["playbook"]).endswith("/phoronix_test_suite/ansible/setup_plugin.yml"):
    ...
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/lb_controller/test_controller.py::test_controller_merges_plugin_extravars_into_setup -q`
Expected: FAIL because the playbook is still named `setup.yml`.

**Step 3: Rename plugin playbooks + update SETUP_PLAYBOOK constants**

```python
# example: lb_plugins/plugins/stress_ng/plugin.py
SETUP_PLAYBOOK = Path(__file__).parent / "ansible" / "setup_plugin.yml"
```

Apply to plugins currently using `ansible/setup.yml`:
- `stress_ng`, `hpl`, `unixbench`, `fio`, `yabs`, `geekbench`, `stream`, `dd`, `sysbench`, `phoronix_test_suite` (plus any others found by `find lb_plugins/plugins -name setup.yml`).

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/lb_controller/test_controller.py::test_controller_merges_plugin_extravars_into_setup -q`
Expected: PASS

**Step 5: Commit**

```bash
git add lb_plugins/plugins/**/ansible/setup_plugin.yml lb_plugins/plugins/**/plugin.py tests/unit/lb_controller/test_controller.py
git commit -m "refactor: rename plugin setup playbooks to setup_plugin"
```

### Task 3: Add Per-Workload Collector Disablement

**Files:**
- Modify: `lb_runner/models/config.py`
- Modify: `lb_runner/engine/metrics.py`
- Modify: `lb_runner/engine/executor.py`
- Modify: `lb_runner/engine/runner.py`
- Test: `tests/unit/lb_runner/engine_tests/test_metric_manager_collectors.py`

**Step 1: Write the failing test**

```python
from unittest.mock import MagicMock

from lb_runner.engine.metrics import MetricManager
from lb_runner.api import BenchmarkConfig


def test_collectors_disabled_skips_registry() -> None:
    registry = MagicMock()
    registry.create_collectors.side_effect = AssertionError("should not be called")
    mm = MetricManager(registry=registry, output_manager=MagicMock(), host_name="host")

    session = mm.begin_repetition(
        BenchmarkConfig(),
        test_name="dummy",
        repetition=1,
        total_repetitions=1,
        current_run_id="run-1",
        collectors_enabled=False,
    )

    assert session.collectors == []
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/lb_runner/engine_tests/test_metric_manager_collectors.py -q`
Expected: FAIL because `collectors_enabled` is not supported.

**Step 3: Write minimal implementation**

```python
# lb_runner/models/config.py
class WorkloadConfig(BaseModel):
    ...
    collectors_enabled: bool = Field(default=True, description="Enable metric collectors for this workload")

# lb_runner/engine/metrics.py
    def begin_repetition(..., collectors_enabled: bool = True) -> "MetricSession":
        collectors = [] if not collectors_enabled else self.create_collectors(config)
        log_handler = self.attach_event_logger(...)
        return MetricSession(metric_manager=self, collectors=collectors, log_handler=log_handler)

# lb_runner/engine/executor.py
    def execute(..., collectors_enabled: bool = True) -> Dict[str, Any]:
        metric_session = self.context.metric_manager.begin_repetition(..., collectors_enabled=collectors_enabled)

# lb_runner/engine/runner.py
    outcome = executor.run_attempt(..., collectors_enabled=workload_cfg.collectors_enabled)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/lb_runner/engine_tests/test_metric_manager_collectors.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add lb_runner/models/config.py lb_runner/engine/metrics.py lb_runner/engine/executor.py lb_runner/engine/runner.py tests/unit/lb_runner/engine_tests/test_metric_manager_collectors.py
git commit -m "feat: allow per-workload collector disablement"
```

### Task 4: Replace peva_faas k6_* Config Fields with k3s_* Fields

**Files:**
- Modify: `lb_plugins/plugins/peva_faas/config.py`
- Test: `tests/unit/lb_plugins/peva_faas/test_dfaas_config.py`

**Step 1: Write the failing test**

```python
# tests/unit/lb_plugins/peva_faas/test_dfaas_config.py
config_path.write_text(
    "\n".join([
        "common:",
        "  timeout_buffer: 5",
        "plugins:",
        "  peva_faas:",
        "    k3s_host: \"10.0.0.50\"",
        ...
    ])
)

config = DfaasConfig(...)
assert config.k3s_host == "10.0.0.50"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_dfaas_config.py -q`
Expected: FAIL because `k3s_host` does not exist.

**Step 3: Write minimal implementation**

```python
# lb_plugins/plugins/peva_faas/config.py
k3s_host: str = Field(default="127.0.0.1", description="k3s/OpenFaaS host address")
k3s_user: str = Field(default="ubuntu", description="SSH user for k3s host")
k3s_ssh_key: str = Field(default="~/.ssh/id_rsa", description="SSH private key path")
k3s_port: int = Field(default=22, ge=1, le=65535, description="SSH port for k3s host")
```

Remove k6_* fields and remove `_normalize_k6_workspace_root` and the `k6_port` validation in `_validate_ports`.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_dfaas_config.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add lb_plugins/plugins/peva_faas/config.py tests/unit/lb_plugins/peva_faas/test_dfaas_config.py
git commit -m "feat(peva_faas): replace k6_* config with k3s_*"
```

### Task 5: Migrate PEVA-faas Tests from k6_* to k3s_* (Non‑K6Runner)

**Files:**
- Modify: `tests/unit/lb_plugins/peva_faas/test_dfaas_generator.py`
- Modify: `tests/unit/lb_plugins/peva_faas/test_dfaas_run_execution.py`
- Modify: `tests/unit/lb_plugins/peva_faas/test_dfaas_url_resolution.py`
- Modify: `tests/unit/lb_plugins/peva_faas/test_dfaas_playbooks.py`
- Modify: `tests/e2e/test_dfaas_multipass_e2e.py` (only if unit checks depend on it; otherwise leave for later)
- Modify: any other `tests/**/peva_faas` files referencing `k6_*` (use `rg -n "k6_" tests/unit/lb_plugins/peva_faas`).

**Step 1: Write the failing test update**

Replace `k6_*` usages with `k3s_*` in test inputs/expected values (e.g., config fixtures, expected defaults).

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas -q`
Expected: FAIL until code is updated in Tasks 4 and 6/7.

**Step 3: Apply minimal test updates**

Update assertions to the new field names:

```python
assert config.k3s_host == "10.0.0.50"
```

**Step 4: Re-run unit tests**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_dfaas_generator.py -q`
Expected: PASS (or new failures isolated to K6Runner tests handled in Task 6).

**Step 5: Commit**

```bash
git add tests/unit/lb_plugins/peva_faas
git commit -m "test(peva_faas): migrate k6_* fields to k3s_*"
```

### Task 6: Make K6Runner Local and Update Generator Execution Flow

**Files:**
- Modify: `lb_plugins/plugins/peva_faas/services/k6_runner.py`
- Modify: `lb_plugins/plugins/peva_faas/generator.py`
- Modify: `lb_plugins/plugins/peva_faas/services/run_execution.py`
- Modify: `lb_plugins/plugins/peva_faas/services/run_execution.py` (context output_dir)
- Remove: `tests/unit/lb_plugins/peva_faas/test_dfaas_k6_runner_fabric.py`
- Create: `tests/unit/lb_plugins/peva_faas/test_dfaas_k6_runner_local.py`

**Step 1: Write the failing test**

```python
from pathlib import Path
from unittest.mock import MagicMock, patch

from lb_plugins.plugins.peva_faas.services.k6_runner import K6Runner


def test_k6_runner_executes_locally(tmp_path: Path) -> None:
    runner = K6Runner(gateway_url="http://gw", duration="1s", log_stream_enabled=False)
    with patch("subprocess.Popen") as popen:
        proc = MagicMock()
        proc.stdout = ["ok\n"]
        proc.wait.return_value = 0
        popen.return_value = proc

        result = runner.execute(
            config_id="cfg",
            script="export default function() {}",
            target_name="target",
            run_id="run",
            metric_ids={},
            output_root=tmp_path,
        )

    assert (tmp_path / "k6" / "target" / "run" / "cfg" / "summary.json").exists()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_dfaas_k6_runner_local.py -q`
Expected: FAIL because K6Runner is still Fabric-based.

**Step 3: Write minimal implementation**

```python
# lb_plugins/plugins/peva_faas/services/k6_runner.py
class K6Runner:
    def __init__(self, gateway_url: str, duration: str, log_stream_enabled: bool = False, log_callback: Any | None = None, log_to_logger: bool = True) -> None:
        ...

    def execute(..., output_root: Path, ...) -> K6RunResult:
        workspace = output_root / "k6" / target_name / run_id / config_id
        script_path = workspace / "script.js"
        summary_path = workspace / "summary.json"
        log_path = workspace / "k6.log"
        ...
        cmd = ["k6", "run", "--summary-export", str(summary_path), str(script_path)]
        proc = subprocess.Popen(..., stdout=PIPE, stderr=STDOUT, text=True)
        ...
```

Update `DfaasGenerator` to construct K6Runner without SSH params and to validate `k6` binary availability. Update `DfaasRunContext` to carry `output_dir` and pass it into `K6Runner.execute(...)` from `DfaasConfigExecutor`.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_dfaas_k6_runner_local.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add lb_plugins/plugins/peva_faas/services/k6_runner.py lb_plugins/plugins/peva_faas/generator.py lb_plugins/plugins/peva_faas/services/run_execution.py tests/unit/lb_plugins/peva_faas/test_dfaas_k6_runner_local.py
git rm tests/unit/lb_plugins/peva_faas/test_dfaas_k6_runner_fabric.py
git commit -m "feat(peva_faas): run k6 locally"
```

### Task 7: Update peva_faas Ansible Playbooks and Wiring

**Files:**
- Rename: `lb_plugins/plugins/peva_faas/ansible/setup_global.yml` → `setup_plugin.yml`
- Rename: `lb_plugins/plugins/peva_faas/ansible/tasks/setup_target_tasks.yml` → `setup_k3s_tasks.yml`
- Modify: `lb_plugins/plugins/peva_faas/ansible/setup_plugin.yml`
- Modify: `lb_plugins/plugins/peva_faas/ansible/tasks/install_k6.yml`
- Modify: `lb_plugins/plugins/peva_faas/plugin.py`

**Step 1: Write failing playbook-path test update**

Update any tests referencing `setup_global.yml` to `setup_plugin.yml` and run the specific test(s) to fail until playbooks are renamed.

**Step 2: Implement playbook changes**

- `setup_plugin.yml`: add `k3s_*` host via `add_host`, install k6 on `hosts: all`, configure k3s via `hosts: k3s_nodes` and import `tasks/setup_k3s_tasks.yml`.
- `install_k6.yml`: drop workspace creation step (no `k6_workspace_root`).
- `plugin.py`: set `SETUP_PLAYBOOK = .../ansible/setup_plugin.yml`.

**Step 3: Run playbook tests**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_dfaas_playbooks.py -q`
Expected: PASS

**Step 4: Commit**

```bash
git add lb_plugins/plugins/peva_faas/ansible lb_plugins/plugins/peva_faas/plugin.py tests/unit/lb_plugins/peva_faas/test_dfaas_playbooks.py
git commit -m "refactor(peva_faas): rename and reshape setup_plugin playbook"
```

### Task 8: Remove K6 Remote Collect Playbooks (Local Artifacts Only)

**Files:**
- Modify: `lb_plugins/plugins/peva_faas/plugin.py`
- Remove or no-op: `lb_plugins/plugins/peva_faas/ansible/collect/pre.yml`
- Remove or no-op: `lb_plugins/plugins/peva_faas/ansible/collect/post.yml`
- Modify: `tests/unit/lb_controller/test_collect_playbook.py`

**Step 1: Write failing test update**

Update `test_dfaas_plugin_collect_post_playbook` to assert that the PEVA-faas collect post is absent or empty.

**Step 2: Implement change**

Set `COLLECT_PRE_PLAYBOOK = None` and `COLLECT_POST_PLAYBOOK = None` in `DfaasPlugin`, and remove or empty the collect playbooks.

**Step 3: Run test**

Run: `uv run pytest tests/unit/lb_controller/test_collect_playbook.py -q`
Expected: PASS

**Step 4: Commit**

```bash
git add lb_plugins/plugins/peva_faas/plugin.py lb_plugins/plugins/peva_faas/ansible/collect tests/unit/lb_controller/test_collect_playbook.py
git commit -m "refactor(peva_faas): drop remote k6 collect playbooks"
```

### Task 9: Update README Diagram and Text

**Files:**
- Modify: `lb_plugins/plugins/peva_faas/README.md`

**Step 1: Write the failing doc expectation**

Update the diagram and text to show three nodes: controller, runner/k6, and k3s/OpenFaaS/Prometheus.

**Step 2: Run doc lint (if any)**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_peva_faas_identity.py -q`
Expected: PASS (no doc lint available).

**Step 3: Commit**

```bash
git add lb_plugins/plugins/peva_faas/README.md
git commit -m "docs(peva_faas): update architecture diagram"
```
