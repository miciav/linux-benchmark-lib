# ISSUE-002: Plugin Tests Misplaced in `tests/unit/common/`

## Summary

Multiple workload plugin tests are located in `tests/unit/common/` instead of the designated `tests/unit/lb_plugins/` directory. This violates the project's module boundary conventions and makes it difficult to run plugin-specific tests.

## Current State

### Plugin Tests in Wrong Location

```
tests/unit/common/
├── test_dd_plugin.py           # Should be in lb_plugins/
├── test_fio_plugin.py          # Should be in lb_plugins/
├── test_fio_plugin_export.py   # Should be in lb_plugins/
├── test_geekbench_plugin.py    # Should be in lb_plugins/
├── test_stress_ng_plugin.py    # Should be in lb_plugins/
├── test_sysbench_plugin.py     # Should be in lb_plugins/
├── test_unixbench_plugin.py    # Should be in lb_plugins/
├── test_yabs_plugin.py         # Should be in lb_plugins/
├── test_plugin_registry.py     # Could stay (registry is lb_plugins.api)
├── test_plugin_installer.py    # Could stay (installer logic)
└── ... (other unrelated tests)
```

### Correct Location Already Has Some Tests

```
tests/unit/lb_plugins/
├── test_dfaas_cooldown.py
├── test_dfaas_docs.py
├── test_dfaas_grafana_dashboard.py
├── test_dfaas_imports.py
├── test_dfaas_metrics_collector.py
├── test_dfaas_playbooks.py
├── test_dfaas_queries.py
├── test_dfaas_result_builder.py
├── test_grafana_assets.py
└── test_command_base.py
```

## Problem Analysis

1. **Inconsistent organization**: DFaaS plugin tests are correctly in `lb_plugins/`, but other plugins are in `common/`.

2. **Test discovery issues**: Running `pytest tests/unit/lb_plugins/` misses 8+ plugin test files.

3. **CLAUDE.md violation**: The project convention states tests should be in subdirs matching the module (`lb_runner/`, `lb_controller/`, etc.).

4. **Historical accumulation**: The `common/` folder appears to be a dumping ground for tests that predate the current structure.

## Proposed Resolution

### Target Structure

```
tests/unit/lb_plugins/
├── plugins/
│   ├── test_dd_plugin.py
│   ├── test_fio_plugin.py
│   ├── test_fio_plugin_export.py
│   ├── test_geekbench_plugin.py
│   ├── test_stress_ng_plugin.py
│   ├── test_sysbench_plugin.py
│   ├── test_unixbench_plugin.py
│   └── test_yabs_plugin.py
├── dfaas/
│   ├── test_dfaas_cooldown.py
│   ├── test_dfaas_docs.py
│   └── ... (existing dfaas tests)
├── test_plugin_registry.py    # API-level tests
├── test_plugin_installer.py   # Installer tests
├── test_command_base.py
└── test_grafana_assets.py
```

## Action Plan

### Step 1: Create Subdirectory Structure

```bash
mkdir -p tests/unit/lb_plugins/plugins
mkdir -p tests/unit/lb_plugins/dfaas
touch tests/unit/lb_plugins/plugins/__init__.py
touch tests/unit/lb_plugins/dfaas/__init__.py
```

**Estimated effort:** 5 minutes

### Step 2: Relocate Plugin Tests

```bash
# Move individual plugin tests
git mv tests/unit/common/test_dd_plugin.py tests/unit/lb_plugins/plugins/
git mv tests/unit/common/test_fio_plugin.py tests/unit/lb_plugins/plugins/
git mv tests/unit/common/test_fio_plugin_export.py tests/unit/lb_plugins/plugins/
git mv tests/unit/common/test_geekbench_plugin.py tests/unit/lb_plugins/plugins/
git mv tests/unit/common/test_stress_ng_plugin.py tests/unit/lb_plugins/plugins/
git mv tests/unit/common/test_sysbench_plugin.py tests/unit/lb_plugins/plugins/
git mv tests/unit/common/test_unixbench_plugin.py tests/unit/lb_plugins/plugins/
git mv tests/unit/common/test_yabs_plugin.py tests/unit/lb_plugins/plugins/

# Move registry and installer to lb_plugins root
git mv tests/unit/common/test_plugin_registry.py tests/unit/lb_plugins/
git mv tests/unit/common/test_plugin_installer.py tests/unit/lb_plugins/
```

**Estimated effort:** 15 minutes

### Step 3: Reorganize DFaaS Tests

```bash
# Move existing dfaas tests to subdirectory
git mv tests/unit/lb_plugins/test_dfaas_*.py tests/unit/lb_plugins/dfaas/
```

**Estimated effort:** 10 minutes

### Step 4: Update Imports (if necessary)

Check each moved file for relative imports that need adjustment:

```python
# Before (if using relative)
from ..common.fixtures import some_fixture

# After
from tests.fixtures import some_fixture
```

**Estimated effort:** 30 minutes

### Step 5: Verify Test Discovery

```bash
# All plugin tests should now be discoverable
pytest tests/unit/lb_plugins/ --collect-only

# Specific plugin
pytest tests/unit/lb_plugins/plugins/test_fio_plugin.py -v
```

**Estimated effort:** 10 minutes

### Step 6: Update pytest Markers

Ensure plugin tests have consistent markers:

```python
# In each plugin test file
pytestmark = pytest.mark.unit_plugins
```

Add to `pyproject.toml`:
```toml
[tool.pytest.ini_options]
markers = [
    "unit_plugins: plugin unit tests",
    "unit_plugins_dfaas: DFaaS plugin tests",
    "unit_plugins_stress: stress-ng plugin tests",
    "unit_plugins_io: fio/dd I/O plugin tests",
]
```

**Estimated effort:** 20 minutes

## Files to Relocate

| Current Path | New Path |
|--------------|----------|
| `tests/unit/common/test_dd_plugin.py` | `tests/unit/lb_plugins/plugins/test_dd_plugin.py` |
| `tests/unit/common/test_fio_plugin.py` | `tests/unit/lb_plugins/plugins/test_fio_plugin.py` |
| `tests/unit/common/test_fio_plugin_export.py` | `tests/unit/lb_plugins/plugins/test_fio_plugin_export.py` |
| `tests/unit/common/test_geekbench_plugin.py` | `tests/unit/lb_plugins/plugins/test_geekbench_plugin.py` |
| `tests/unit/common/test_stress_ng_plugin.py` | `tests/unit/lb_plugins/plugins/test_stress_ng_plugin.py` |
| `tests/unit/common/test_sysbench_plugin.py` | `tests/unit/lb_plugins/plugins/test_sysbench_plugin.py` |
| `tests/unit/common/test_unixbench_plugin.py` | `tests/unit/lb_plugins/plugins/test_unixbench_plugin.py` |
| `tests/unit/common/test_yabs_plugin.py` | `tests/unit/lb_plugins/plugins/test_yabs_plugin.py` |
| `tests/unit/common/test_plugin_registry.py` | `tests/unit/lb_plugins/test_plugin_registry.py` |
| `tests/unit/common/test_plugin_installer.py` | `tests/unit/lb_plugins/test_plugin_installer.py` |

## Success Criteria

1. `pytest tests/unit/lb_plugins/ --collect-only` discovers all plugin tests
2. `pytest tests/unit/common/` contains no plugin-related tests
3. All tests pass after relocation
4. CI pipelines updated if they reference specific paths

## Risk Assessment

- **Low risk**: File relocation with git preserves history
- **Medium risk**: Import path updates might break tests (verify with full test run)

## Dependencies

- None (can proceed immediately)

## References

- CLAUDE.md: Test Organization section
- ANALYSIS.md Section 5: Test Suite Fragmentation
