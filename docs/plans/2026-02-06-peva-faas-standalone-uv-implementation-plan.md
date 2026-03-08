# PEVA-FAAS Standalone UV Repo Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a standalone PEVA-FAAS repository that does not depend on `linux-benchmark-lib`, keeps namespace compatibility, supports IDE/debug workflows, and includes Ansible playbooks in milestone 1.

**Architecture:** Create a new repo with the same Python package namespace (`lb_plugins.plugins.peva_faas`) and copy plugin code/assets/tests into it. Replace monorepo-only dependencies with local adapters and provide dedicated debug CLI entrypoints (`debug-run`, `debug-step`, `debug-replay`). Keep one `uv` profile for both dev and live use.

**Tech Stack:** Python 3.13, uv, pytest, mypy, ruff, black, duckdb, prometheus-client, ansible-core, k6 (system binary), OpenFaaS/k3s remote target.

## Preconditions

- Target repo path: `/Users/micheleciavotta/Downloads/peva-faas-standalone` (adjust if needed).
- Local tools installed: `uv`, `git`, `k6`.
- Current repo available for manual copy source: `/Users/micheleciavotta/Downloads/linux-benchmark-lib`.

### Task 1: Bootstrap Standalone Repo Skeleton

**Files:**
- Create: `/Users/micheleciavotta/Downloads/peva-faas-standalone/pyproject.toml`
- Create: `/Users/micheleciavotta/Downloads/peva-faas-standalone/README.md`
- Create: `/Users/micheleciavotta/Downloads/peva-faas-standalone/lb_plugins/plugins/peva_faas/__init__.py`
- Create: `/Users/micheleciavotta/Downloads/peva-faas-standalone/tests/unit/lb_plugins/peva_faas/test_imports.py`

**Step 1: Write the failing test**

```python
def test_namespace_imports() -> None:
    from lb_plugins.plugins.peva_faas import __name__ as module_name

    assert module_name == "lb_plugins.plugins.peva_faas"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_imports.py -q`
Expected: FAIL with `ModuleNotFoundError` for `lb_plugins`.

**Step 3: Write minimal implementation**

Create namespace package dirs and empty `__init__.py` files so import resolves.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_imports.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add pyproject.toml README.md lb_plugins tests
git commit -m "chore: bootstrap standalone peva_faas namespace repo"
```

### Task 2: Configure UV Single Profile and CLI Entrypoints

**Files:**
- Modify: `/Users/micheleciavotta/Downloads/peva-faas-standalone/pyproject.toml`
- Create: `/Users/micheleciavotta/Downloads/peva-faas-standalone/lb_plugins/plugins/peva_faas/debug_cli.py`
- Test: `/Users/micheleciavotta/Downloads/peva-faas-standalone/tests/unit/lb_plugins/peva_faas/test_debug_cli.py`

**Step 1: Write the failing test**

```python
from click.testing import CliRunner
from lb_plugins.plugins.peva_faas.debug_cli import cli


def test_debug_run_help() -> None:
    result = CliRunner().invoke(cli, ["debug-run", "--help"])
    assert result.exit_code == 0
    assert "--dry-run" in result.output
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_debug_cli.py -q`
Expected: FAIL (missing module/command).

**Step 3: Write minimal implementation**

Add dependencies in `project.optional-dependencies.dev` (single profile):
- `pytest`, `pytest-cov`, `mypy`, `ruff`, `black`
- `duckdb`, `prometheus-client`, `ansible-core`, `click`, `pydantic`, `pyyaml`

Add scripts:
- `peva-debug-run = "lb_plugins.plugins.peva_faas.debug_cli:debug_run_main"`
- `peva-debug-step = "lb_plugins.plugins.peva_faas.debug_cli:debug_step_main"`
- `peva-debug-replay = "lb_plugins.plugins.peva_faas.debug_cli:debug_replay_main"`

Implement `click` commands with `--dry-run/--live` flags and stub output.

**Step 4: Run test to verify it passes**

Run: `uv sync --extra dev && uv run pytest tests/unit/lb_plugins/peva_faas/test_debug_cli.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add pyproject.toml lb_plugins/plugins/peva_faas/debug_cli.py tests/unit/lb_plugins/peva_faas/test_debug_cli.py
git commit -m "feat: add uv single-profile setup and debug cli entrypoints"
```

### Task 3: Port Core Plugin Files with Namespace Preservation

**Files:**
- Create/Modify under: `/Users/micheleciavotta/Downloads/peva-faas-standalone/lb_plugins/plugins/peva_faas/`
- Include: `config.py`, `generator.py`, `plugin.py`, `context.py`, `exceptions.py`, `queries.py`, `queries.yml`
- Include services: `/services/*.py`
- Include strategies: `/strategies/*.py`
- Test: `/Users/micheleciavotta/Downloads/peva-faas-standalone/tests/unit/lb_plugins/peva_faas/test_ported_core_imports.py`

**Step 1: Write the failing test**

```python
def test_ported_core_modules_import() -> None:
    from lb_plugins.plugins.peva_faas import config, generator, plugin  # noqa: F401
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_ported_core_imports.py -q`
Expected: FAIL on missing modules.

**Step 3: Write minimal implementation**

Copy files manually from monorepo plugin path, preserving relative package layout.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_ported_core_imports.py -q`
Expected: PASS or first actionable missing dependency error.

**Step 5: Commit**

```bash
git add lb_plugins/plugins/peva_faas tests/unit/lb_plugins/peva_faas/test_ported_core_imports.py
git commit -m "feat: port peva_faas core modules into standalone repo"
```

### Task 4: Remove Monorepo Couplings via Local Adapters

**Files:**
- Create: `/Users/micheleciavotta/Downloads/peva-faas-standalone/lb_plugins/plugins/peva_faas/local_adapters.py`
- Modify: `/Users/micheleciavotta/Downloads/peva-faas-standalone/lb_plugins/plugins/peva_faas/config.py`
- Modify: `/Users/micheleciavotta/Downloads/peva-faas-standalone/lb_plugins/plugins/peva_faas/generator.py`
- Modify: `/Users/micheleciavotta/Downloads/peva-faas-standalone/lb_plugins/plugins/peva_faas/services/run_execution.py`
- Test: `/Users/micheleciavotta/Downloads/peva-faas-standalone/tests/unit/lb_plugins/peva_faas/test_standalone_adapters.py`

**Step 1: Write the failing test**

```python
def test_standalone_does_not_require_lb_runner_import() -> None:
    import importlib

    mod = importlib.import_module("lb_plugins.plugins.peva_faas.local_adapters")
    assert hasattr(mod, "resolve_output_root")
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_standalone_adapters.py -q`
Expected: FAIL, module missing.

**Step 3: Write minimal implementation**

Implement adapter functions for:
- logging setup hook
- default output root resolution
- optional no-op integration glue expected by plugin flow

Patch imports in core files to use local adapters, not monorepo modules.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_standalone_adapters.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add lb_plugins/plugins/peva_faas/local_adapters.py lb_plugins/plugins/peva_faas/config.py lb_plugins/plugins/peva_faas/generator.py lb_plugins/plugins/peva_faas/services/run_execution.py tests/unit/lb_plugins/peva_faas/test_standalone_adapters.py
git commit -m "refactor: isolate standalone adapters from monorepo dependencies"
```

### Task 5: Implement Debug Run/Step/Replay Behavior

**Files:**
- Modify: `/Users/micheleciavotta/Downloads/peva-faas-standalone/lb_plugins/plugins/peva_faas/debug_cli.py`
- Create: `/Users/micheleciavotta/Downloads/peva-faas-standalone/lb_plugins/plugins/peva_faas/debug_runtime.py`
- Test: `/Users/micheleciavotta/Downloads/peva-faas-standalone/tests/unit/lb_plugins/peva_faas/test_debug_runtime.py`

**Step 1: Write the failing test**

```python
def test_debug_run_dry_mode_writes_manifest(tmp_path) -> None:
    from lb_plugins.plugins.peva_faas.debug_runtime import run_dry

    output = run_dry(tmp_path)
    assert (output / "diagnostics.json").exists()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_debug_runtime.py -q`
Expected: FAIL, function not found.

**Step 3: Write minimal implementation**

Implement:
- `run_dry(...)` to build minimal plan and write diagnostics/result stubs
- `run_live(...)` to validate k6 presence and call existing execution path
- `replay_checkpoint(...)` to reload checkpoint path and run one decision cycle

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_debug_runtime.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add lb_plugins/plugins/peva_faas/debug_cli.py lb_plugins/plugins/peva_faas/debug_runtime.py tests/unit/lb_plugins/peva_faas/test_debug_runtime.py
git commit -m "feat: add debug run, step, and replay execution flows"
```

### Task 6: Include Ansible Assets for Milestone 1

**Files:**
- Copy: `/Users/micheleciavotta/Downloads/peva-faas-standalone/lb_plugins/plugins/peva_faas/ansible/**`
- Copy: `/Users/micheleciavotta/Downloads/peva-faas-standalone/lb_plugins/plugins/peva_faas/grafana/**`
- Test: `/Users/micheleciavotta/Downloads/peva-faas-standalone/tests/unit/lb_plugins/peva_faas/test_ansible_assets_present.py`

**Step 1: Write the failing test**

```python
from pathlib import Path


def test_ansible_playbooks_present() -> None:
    root = Path("lb_plugins/plugins/peva_faas/ansible")
    assert (root / "setup_target.yml").exists()
    assert (root / "setup_k6.yml").exists()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_ansible_assets_present.py -q`
Expected: FAIL, missing files.

**Step 3: Write minimal implementation**

Copy ansible manifests, tasks, vars, templates, and grafana dashboards from monorepo plugin.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_ansible_assets_present.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add lb_plugins/plugins/peva_faas/ansible lb_plugins/plugins/peva_faas/grafana tests/unit/lb_plugins/peva_faas/test_ansible_assets_present.py
git commit -m "feat: include milestone-1 ansible and grafana assets"
```

### Task 7: Add Local and Live Configs + k6 Guardrail

**Files:**
- Create: `/Users/micheleciavotta/Downloads/peva-faas-standalone/config/dev.local.yml`
- Create: `/Users/micheleciavotta/Downloads/peva-faas-standalone/config/live.remote.yml`
- Modify: `/Users/micheleciavotta/Downloads/peva-faas-standalone/lb_plugins/plugins/peva_faas/debug_runtime.py`
- Test: `/Users/micheleciavotta/Downloads/peva-faas-standalone/tests/unit/lb_plugins/peva_faas/test_k6_guardrail.py`

**Step 1: Write the failing test**

```python
def test_live_mode_requires_k6(monkeypatch) -> None:
    from lb_plugins.plugins.peva_faas.debug_runtime import assert_k6_available

    monkeypatch.setenv("PATH", "")
    try:
        assert_k6_available()
    except RuntimeError as exc:
        assert "k6" in str(exc).lower()
    else:
        raise AssertionError("expected RuntimeError")
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_k6_guardrail.py -q`
Expected: FAIL.

**Step 3: Write minimal implementation**

Add explicit binary check and clear error text with remediation command hint.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_k6_guardrail.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add config/dev.local.yml config/live.remote.yml lb_plugins/plugins/peva_faas/debug_runtime.py tests/unit/lb_plugins/peva_faas/test_k6_guardrail.py
git commit -m "feat: add dev/live configs and k6 availability guardrail"
```

### Task 8: Port Core Unit Tests and Add Smoke Tests

**Files:**
- Copy/Adjust: `/Users/micheleciavotta/Downloads/peva-faas-standalone/tests/unit/lb_plugins/peva_faas/test_peva_faas_*.py`
- Create: `/Users/micheleciavotta/Downloads/peva-faas-standalone/tests/smoke/test_debug_dry_run.py`
- Create: `/Users/micheleciavotta/Downloads/peva-faas-standalone/tests/smoke/test_debug_live_marker.py`

**Step 1: Write the failing smoke test**

```python
import subprocess


def test_debug_run_dry_smoke() -> None:
    proc = subprocess.run(
        ["uv", "run", "peva-debug-run", "--config", "config/dev.local.yml", "--dry-run"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/smoke/test_debug_dry_run.py -q`
Expected: FAIL until CLI/runtime is fully wired.

**Step 3: Write minimal implementation**

Adjust CLI/runtime output paths and config loading until smoke passes.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas -q`
Run: `uv run pytest tests/smoke/test_debug_dry_run.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add tests/unit/lb_plugins/peva_faas tests/smoke
git commit -m "test: port core peva_faas tests and add dry-run smoke coverage"
```

### Task 9: Add Sync Contract and Developer Docs

**Files:**
- Create: `/Users/micheleciavotta/Downloads/peva-faas-standalone/SYNC_NOTES.md`
- Modify: `/Users/micheleciavotta/Downloads/peva-faas-standalone/README.md`
- Create: `/Users/micheleciavotta/Downloads/peva-faas-standalone/docs/debug-workflow.md`

**Step 1: Write the failing doc test**

```python
from pathlib import Path


def test_sync_notes_exists() -> None:
    assert Path("SYNC_NOTES.md").exists()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_sync_docs.py -q`
Expected: FAIL, file missing.

**Step 3: Write minimal implementation**

Document:
- authoritative file list for manual copy
- copy checklist before and after sync
- standard commands (`uv sync --extra dev`, `uv run pytest -q`, `uv run peva-debug-run ...`)
- Ansible playbook invocation examples.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/lb_plugins/peva_faas/test_sync_docs.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add README.md SYNC_NOTES.md docs/debug-workflow.md tests/unit/lb_plugins/peva_faas/test_sync_docs.py
git commit -m "docs: define manual sync contract and standalone debug workflow"
```

### Task 10: Final Verification Gate

**Files:**
- Modify (if needed): `/Users/micheleciavotta/Downloads/peva-faas-standalone/pyproject.toml`

**Step 1: Run quality checks**

Run: `uv run ruff check .`
Expected: PASS.

**Step 2: Run typing**

Run: `uv run mypy lb_plugins`
Expected: PASS.

**Step 3: Run full tests**

Run: `uv run pytest -q`
Expected: PASS.

**Step 4: Run smoke command manually**

Run: `uv run peva-debug-run --config config/dev.local.yml --dry-run`
Expected: exit code 0 and generated diagnostics/result artifacts.

**Step 5: Commit**

```bash
git add -u
git commit -m "chore: finalize standalone peva_faas milestone-1 verification"
```

## Notes for Milestone 2 (Out of Scope Here)

- Add Multipass VM build wrapper script that invokes included playbooks.
- Add optional VM snapshot/image reuse flow after first successful setup.
- Optionally add remote smoke checks against k3s/OpenFaaS readiness.
