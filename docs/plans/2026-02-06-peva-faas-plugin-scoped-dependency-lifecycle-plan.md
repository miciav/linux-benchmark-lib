# Plugin-Scoped Dependency Lifecycle (PEVA-FAAS First) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make `duckdb` and `pyarrow` plugin-scoped dependencies for `peva_faas` (not global project deps), with deterministic install/uninstall behavior in setup/teardown lifecycle.

**Architecture:** Introduce a generic plugin dependency contract at `PluginAssetConfig` level, resolve enabled-plugin UV extras at controller runtime, and install them during global setup via `uv sync --extra ...`. Keep plugin setup/teardown for plugin runtime assets (k6/faas-cli and plugin data cleanup), and add generator preflight checks for clear failures when lifecycle is skipped.

**Tech Stack:** Python 3.12+, Pydantic v2, Ansible, UV, pytest.

## Decision Summary

- **Option A (minimal):** Install `duckdb/pyarrow` in `peva_faas` setup playbook with `uv pip install`.
- **Option B (recommended):** Use plugin-scoped UV extras resolved from enabled plugins, then install in global setup with `uv sync --extra`.
- **Option C (future):** Per-plugin isolated venv per workload.

Recommendation: **Option B now**, because it is generic, deterministic (lock-backed), and reusable for all plugins with Python-only deps.

## Constraints And Invariants

- `setup_plugin.yml` remains the plugin lifecycle setup entrypoint.
- No plugin-specific package should stay in `[project.dependencies]`.
- Install path must work for remote runs (controller global setup) and not depend on ad-hoc pip state.
- Teardown must not delete unrelated user files; cleanup must be explicit and opt-in.

### Task 1: Add Generic Plugin Dependency Metadata Contract

**Files:**
- Modify: `lb_plugins/plugin_assets.py`
- Modify: `lb_plugins/interface.py`
- Test: `tests/unit/lb_plugins/test_plugin_dependency_contract.py` (new)

**Step 1: Write the failing test**

```python
def test_simple_plugin_exposes_required_uv_extras() -> None:
    class P(SimpleWorkloadPlugin):
        NAME = "p"
        REQUIRED_UV_EXTRAS = ["peva_faas"]
    assert P().get_required_uv_extras() == ["peva_faas"]
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/lb_plugins/test_plugin_dependency_contract.py -q`
Expected: FAIL (`get_required_uv_extras` missing).

**Step 3: Write minimal implementation**

```python
class WorkloadPlugin(ABC):
    def get_required_uv_extras(self) -> List[str]:
        return []

class SimpleWorkloadPlugin(WorkloadPlugin):
    REQUIRED_UV_EXTRAS: List[str] = []
    def get_required_uv_extras(self) -> List[str]:
        return list(self.REQUIRED_UV_EXTRAS)
```

Add `required_uv_extras: list[str]` to `PluginAssetConfig`.

**Step 4: Run test to verify pass**

Run: `uv run pytest tests/unit/lb_plugins/test_plugin_dependency_contract.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add lb_plugins/interface.py lb_plugins/plugin_assets.py tests/unit/lb_plugins/test_plugin_dependency_contract.py
git commit -m "feat(plugins): add generic plugin uv-extra dependency contract"
```

### Task 2: Propagate Dependency Metadata Through Plugin Asset Resolution

**Files:**
- Modify: `lb_plugins/api.py`
- Test: `tests/unit/lb_plugins/test_plugin_dependency_contract.py`

**Step 1: Write the failing test**

```python
def test_build_plugin_assets_includes_required_uv_extras() -> None:
    plugin = DummyPlugin(required_uv_extras=["peva_faas"])
    assets = _build_plugin_assets(plugin)
    assert assets.required_uv_extras == ["peva_faas"]
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/lb_plugins/test_plugin_dependency_contract.py -q`
Expected: FAIL (`required_uv_extras` not populated).

**Step 3: Write minimal implementation**

Add to `_build_plugin_assets()`:

```python
required_uv_extras=_call_plugin_method(plugin, "get_required_uv_extras", default=[]) or []
```

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/unit/lb_plugins/test_plugin_dependency_contract.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add lb_plugins/api.py tests/unit/lb_plugins/test_plugin_dependency_contract.py
git commit -m "feat(plugins): propagate required uv extras in plugin assets"
```

### Task 3: Resolve Enabled-Plugin Extras In Controller Extravars

**Files:**
- Modify: `lb_controller/engine/run_state_builders.py`
- Test: `tests/unit/lb_controller/test_run_state_builders.py`

**Step 1: Write the failing test**

```python
def test_extravars_builder_collects_uv_extras_for_enabled_workloads(tmp_path):
    cfg = BenchmarkConfig(output_dir=tmp_path / "out")
    cfg.workloads = {"w": WorkloadConfig(plugin="peva_faas", enabled=True)}
    cfg.plugin_assets = {"peva_faas": PluginAssetConfig(required_uv_extras=["peva_faas"])}
    extravars = ExtravarsBuilder(cfg).build(...)
    assert extravars["lb_uv_extras"] == ["peva_faas"]
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/lb_controller/test_run_state_builders.py -q`
Expected: FAIL (`lb_uv_extras` missing).

**Step 3: Write minimal implementation**

In `ExtravarsBuilder.build()`:
- collect enabled workload plugins,
- union `plugin_assets[plugin].required_uv_extras`,
- sort and place in `extravars["lb_uv_extras"]`.

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/unit/lb_controller/test_run_state_builders.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add lb_controller/engine/run_state_builders.py tests/unit/lb_controller/test_run_state_builders.py
git commit -m "feat(controller): resolve plugin uv extras into setup extravars"
```

### Task 4: Install Plugin Extras In Global Setup Playbook

**Files:**
- Modify: `lb_controller/ansible/playbooks/setup.yml`
- Test: `tests/unit/lb_controller/ansible_tests/test_setup_playbook_sync.py`

**Step 1: Write the failing test**

```python
def test_setup_playbook_sync_uses_lb_uv_extras() -> None:
    # assert setup.yml contains uv sync command that references lb_uv_extras
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/lb_controller/ansible_tests/test_setup_playbook_sync.py -q`
Expected: FAIL (no extras support).

**Step 3: Write minimal implementation**

In playbook:
- build `lb_uv_extra_args` from `lb_uv_extras` list,
- use in sync command:

```yaml
cmd: "{{ lb_uv_bin }} sync --frozen --no-dev {{ lb_uv_extra_args }}"
```

with safe default empty args.

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/unit/lb_controller/ansible_tests/test_setup_playbook_sync.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add lb_controller/ansible/playbooks/setup.yml tests/unit/lb_controller/ansible_tests/test_setup_playbook_sync.py
git commit -m "feat(controller): install enabled plugin extras during uv sync"
```

### Task 5: Move PEVA-FAAS Python Deps From Core To Plugin Extra

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Test: `tests/unit/test_project_dependencies.py`

**Step 1: Write the failing test**

```python
def test_peva_faas_deps_are_not_global() -> None:
    deps = _load_project_dependencies()
    assert not any(d.startswith("duckdb") for d in deps)
    assert not any(d.startswith("pyarrow") for d in deps)
```

And:

```python
def test_peva_faas_extra_contains_plugin_deps() -> None:
    extras = _load_pyproject()["project"]["optional-dependencies"]["peva_faas"]
    assert any(d.startswith("duckdb") for d in extras)
    assert any(d.startswith("pyarrow") for d in extras)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_project_dependencies.py -q`
Expected: FAIL (deps still global).

**Step 3: Write minimal implementation**

- Remove `duckdb` and `pyarrow` from `[project.dependencies]`.
- Add:

```toml
[project.optional-dependencies]
peva_faas = ["duckdb>=1.1.0", "pyarrow>=17.0.0"]
```

- Refresh lock: `uv lock`.

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/unit/test_project_dependencies.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add pyproject.toml uv.lock tests/unit/test_project_dependencies.py
git commit -m "build(peva_faas): scope duckdb and pyarrow to peva_faas extra"
```

### Task 6: Declare PEVA-FAAS Extra In Plugin Metadata + Add Preflight Guard

**Files:**
- Modify: `lb_plugins/plugins/peva_faas/plugin.py`
- Modify: `lb_plugins/plugins/peva_faas/generator.py`
- Modify: `tests/unit/lb_plugins/peva_faas/test_peva_faas_identity.py`
- Modify: `tests/unit/lb_plugins/peva_faas/test_peva_faas_generator.py`

**Step 1: Write the failing tests**

```python
def test_peva_faas_plugin_declares_uv_extra() -> None:
    assert DfaasPlugin.REQUIRED_UV_EXTRAS == ["peva_faas"]
```

```python
def test_validate_environment_fails_when_duckdb_missing(monkeypatch):
    # importlib.import_module("duckdb") -> ModuleNotFoundError
    assert generator._validate_environment() is False
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_peva_faas_identity.py tests/unit/lb_plugins/peva_faas/test_peva_faas_generator.py -q`
Expected: FAIL.

**Step 3: Write minimal implementation**

- In plugin class:

```python
REQUIRED_UV_EXTRAS = ["peva_faas"]
```

- In generator `_validate_environment()`:
  - keep `which faas-cli`/`which k6`,
  - add import checks for `duckdb` and `pyarrow` with explicit log error.

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_peva_faas_identity.py tests/unit/lb_plugins/peva_faas/test_peva_faas_generator.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add lb_plugins/plugins/peva_faas/plugin.py lb_plugins/plugins/peva_faas/generator.py tests/unit/lb_plugins/peva_faas/test_peva_faas_identity.py tests/unit/lb_plugins/peva_faas/test_peva_faas_generator.py
git commit -m "feat(peva_faas): declare uv extra and preflight python deps"
```

### Task 7: Add Explicit Plugin Data Cleanup In Teardown

**Files:**
- Modify: `lb_plugins/plugins/peva_faas/ansible/teardown_k6.yml`
- Modify: `lb_plugins/plugins/peva_faas/test_peva_faas_playbooks.py`

**Step 1: Write the failing test**

```python
def test_teardown_k6_playbook_can_cleanup_memory_assets() -> None:
    playbook = _load_playbook("teardown_k6.yml")
    # assert optional cleanup tasks exist for memory db/parquet paths
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_peva_faas_playbooks.py -q`
Expected: FAIL.

**Step 3: Write minimal implementation**

Add opt-in vars and guardrails:
- `peva_faas_memory_cleanup: false`
- `peva_faas_memory_paths: []`
- assert paths under allowed prefixes (`benchmark_results/peva_faas`, `~/.peva_faas-k6`)
- remove with `ansible.builtin.file state=absent` only when flag enabled.

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_peva_faas_playbooks.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add lb_plugins/plugins/peva_faas/ansible/teardown_k6.yml tests/unit/lb_plugins/peva_faas/test_peva_faas_playbooks.py
git commit -m "feat(peva_faas): add safe optional teardown cleanup for memory assets"
```

### Task 8: Documentation + Migration Notes

**Files:**
- Modify: `lb_plugins/plugins/peva_faas/README.md`
- Modify: `README.md` (if plugin dependency policy is documented there)
- Create: `docs/architecture/plugin-dependency-lifecycle.md`
- Test: `tests/unit/lb_plugins/peva_faas/test_peva_faas_docs.py`

**Step 1: Write the failing test**

```python
def test_readme_mentions_plugin_scoped_extra_and_setup_lifecycle() -> None:
    text = readme.read_text()
    assert "optional dependency extra `peva_faas`" in text
    assert "setup_plugin.yml" in text
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_peva_faas_docs.py -q`
Expected: FAIL.

**Step 3: Write minimal documentation**

Document:
- plugin extra strategy (`[project.optional-dependencies].peva_faas`),
- setup/teardown expectations,
- what global setup installs and what plugin teardown cleans.

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_peva_faas_docs.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add lb_plugins/plugins/peva_faas/README.md docs/architecture/plugin-dependency-lifecycle.md tests/unit/lb_plugins/peva_faas/test_peva_faas_docs.py
git commit -m "docs: define plugin-scoped dependency lifecycle and peva_faas migration"
```

### Task 9: Full Verification Gate

**Files:**
- No new files (verification only)

**Step 1: Run targeted suites**

Run:

```bash
uv run pytest \
  tests/unit/lb_plugins/peva_faas \
  tests/unit/lb_controller/test_run_state_builders.py \
  tests/unit/lb_controller/ansible_tests/test_setup_playbook_sync.py \
  tests/unit/lb_plugins/test_plugin_dependency_contract.py \
  tests/unit/test_project_dependencies.py -q
```

Expected: all PASS.

**Step 2: Run lint/type checks for touched files**

Run:

```bash
uv run ruff check lb_plugins lb_controller tests
uv run mypy lb_plugins lb_controller
```

Expected: PASS (or documented pre-existing failures only).

**Step 3: Final commit (if squashing policy required)**

If team policy needs a single integration commit:

```bash
git log --oneline --decorate -n 10
```

Otherwise keep frequent commits.

### Task 10: Cross-Plugin Rollout (Authorization-Gated Final Phase)

**Execution Gate (mandatory):**
- Start this phase **only after** Tasks 1-9 are green for `peva_faas`.
- Start this phase **only with explicit user authorization** in this thread.
- If authorization is not explicitly given, stop after Task 9 and report readiness.

**Files:**
- Modify: plugin files under `lb_plugins/plugins/*/plugin.py` (only where needed)
- Modify: plugin docs under `lb_plugins/plugins/*/README.md` (only where needed)
- Modify: plugin tests under `tests/unit/lb_plugins/*/`
- Modify: `pyproject.toml` and `uv.lock` (only for plugin-specific extras discovered during migration)

**Step 1: Build migration inventory**

Run:

```bash
rg -n "REQUIRED_PIP_PACKAGES|REQUIRED_LOCAL_TOOLS|_validate_environment|get_required_pip_packages" lb_plugins/plugins
```

Create a plugin-by-plugin checklist:
- plugin name
- python deps currently global
- target optional extra name
- setup/teardown impacts
- required tests/docs updates

**Step 2: Migrate one plugin at a time (TDD loop per plugin)**

For each plugin:
1. add failing tests for dependency contract + setup behavior,
2. implement minimal plugin metadata/docs changes,
3. run plugin unit tests + impacted controller tests,
4. commit.

**Step 3: Final cross-plugin verification**

Run:

```bash
uv run pytest tests/unit/lb_plugins tests/unit/lb_controller -q
uv run ruff check lb_plugins lb_controller tests
uv run mypy lb_plugins lb_controller
```

Expected: PASS (or documented pre-existing failures only).

**Step 4: Final rollout report**

Deliver a short matrix:
- migrated plugins,
- extras introduced,
- setup/teardown changes,
- residual plugins not yet migrated and why.

## Rollout Notes

- Backward compatibility: workloads without `required_uv_extras` remain unchanged.
- If a plugin has no extra, `lb_uv_extras` is empty and setup behavior is the same as today.
- PEVA-FAAS can be migrated first; other plugins can adopt the same contract incrementally.
