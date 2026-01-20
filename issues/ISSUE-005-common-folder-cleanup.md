# ISSUE-005: Cleanup and Purpose Definition for `tests/unit/common/`

## Summary

After relocating plugin and controller tests (ISSUE-002, ISSUE-003), the `tests/unit/common/` folder needs review to define its intended purpose. Currently it serves as a catch-all for tests that don't clearly belong elsewhere.

## Current State (Post ISSUE-002 and ISSUE-003)

After relocating plugin and controller tests, these files would remain:

```
tests/unit/common/
├── test_benchmark_config.py        # Config model tests → lb_runner/models?
├── test_cli_docker_status.py       # CLI tests → lb_ui?
├── test_cli_run_summary.py         # CLI tests → lb_ui?
├── test_component_installability.py # Cross-cutting concern
├── test_data_handler.py            # Analytics → lb_analytics?
├── test_env_utils.py               # Common utilities → lb_common
├── test_events.py                  # Event system → lb_runner or lb_common?
├── test_grafana_client.py          # Grafana client → lb_provisioner?
├── test_interactive_selection.py   # UI → lb_ui
├── test_jsonl_handler.py           # Common utility → lb_common
├── test_log_schema.py              # Logging → lb_common
├── test_loki_handler.py            # Loki logging → lb_common
├── test_plugin_export_csv.py       # Plugin export → lb_plugins
├── test_system_info.py             # System info → lb_runner
└── __init__.py
```

## Problem Analysis

1. **No clear purpose**: `common/` has no defined scope, leading to arbitrary placement.

2. **Mixed ownership**: Files test components from different modules (lb_runner, lb_ui, lb_common, lb_analytics).

3. **Naming confusion**: Some tests are for "common" utilities (`lb_common`), others are just misplaced.

## Proposed Resolution

### Option A: Eliminate `common/` Entirely

Relocate all tests to their appropriate module directories:

```
tests/unit/
├── lb_analytics/
│   └── test_data_handler.py
├── lb_common/
│   ├── test_env_utils.py
│   ├── test_events.py
│   ├── test_jsonl_handler.py
│   ├── test_log_schema.py
│   └── test_loki_handler.py
├── lb_plugins/
│   └── test_plugin_export_csv.py
├── lb_provisioner/
│   └── test_grafana_client.py
├── lb_runner/
│   ├── models/
│   │   └── test_benchmark_config.py
│   └── services/
│       └── test_system_info.py
├── lb_ui/
│   ├── test_cli_docker_status.py
│   ├── test_cli_run_summary.py
│   └── test_interactive_selection.py
└── cross_cutting/
    └── test_component_installability.py
```

### Option B: Redefine `common/` as `lb_common/` Tests Only

Keep `common/` but only for tests that specifically test `lb_common/` utilities:

```
tests/unit/common/  → rename to tests/unit/lb_common/
├── test_env_utils.py
├── test_events.py
├── test_jsonl_handler.py
├── test_log_schema.py
└── test_loki_handler.py
```

All other tests relocate to appropriate module directories.

## Recommended: Option A (Eliminate `common/`)

Benefits:
- Clear 1:1 mapping between source and test directories
- No ambiguity about where new tests should go
- Consistent with CLAUDE.md conventions

## Action Plan

### Step 1: Create Missing Directories

```bash
mkdir -p tests/unit/lb_common
mkdir -p tests/unit/lb_runner/models
mkdir -p tests/unit/cross_cutting
touch tests/unit/lb_common/__init__.py
touch tests/unit/lb_runner/models/__init__.py
touch tests/unit/cross_cutting/__init__.py
```

**Estimated effort:** 5 minutes

### Step 2: Relocate lb_common Tests

```bash
git mv tests/unit/common/test_env_utils.py tests/unit/lb_common/
git mv tests/unit/common/test_jsonl_handler.py tests/unit/lb_common/
git mv tests/unit/common/test_log_schema.py tests/unit/lb_common/
git mv tests/unit/common/test_loki_handler.py tests/unit/lb_common/
git mv tests/unit/common/test_events.py tests/unit/lb_common/
```

**Estimated effort:** 10 minutes

### Step 3: Relocate Runner Model Tests

```bash
git mv tests/unit/common/test_benchmark_config.py tests/unit/lb_runner/models/
git mv tests/unit/common/test_system_info.py tests/unit/lb_runner/services/
```

**Estimated effort:** 5 minutes

### Step 4: Relocate UI Tests

```bash
git mv tests/unit/common/test_cli_docker_status.py tests/unit/lb_ui/
git mv tests/unit/common/test_cli_run_summary.py tests/unit/lb_ui/
git mv tests/unit/common/test_interactive_selection.py tests/unit/lb_ui/
```

**Estimated effort:** 5 minutes

### Step 5: Relocate Analytics Tests

```bash
git mv tests/unit/common/test_data_handler.py tests/unit/lb_analytics/
```

**Estimated effort:** 2 minutes

### Step 6: Relocate Provisioner/Plugin Tests

```bash
git mv tests/unit/common/test_grafana_client.py tests/unit/lb_provisioner/
git mv tests/unit/common/test_plugin_export_csv.py tests/unit/lb_plugins/
```

**Estimated effort:** 5 minutes

### Step 7: Handle Cross-Cutting Concerns

```bash
git mv tests/unit/common/test_component_installability.py tests/unit/cross_cutting/
```

**Estimated effort:** 2 minutes

### Step 8: Remove Empty Directory

```bash
rmdir tests/unit/common/  # Only after all files moved
# Or keep __init__.py if directory is referenced elsewhere
```

**Estimated effort:** 2 minutes

### Step 9: Update CI/Documentation

- Check `.github/workflows/` for paths referencing `tests/unit/common/`
- Update any documentation mentioning the directory
- Update CLAUDE.md if it references `common/`

**Estimated effort:** 15 minutes

## Files Relocation Summary

| Current Path | New Path | Rationale |
|--------------|----------|-----------|
| `test_benchmark_config.py` | `lb_runner/models/` | Config model |
| `test_cli_docker_status.py` | `lb_ui/` | CLI functionality |
| `test_cli_run_summary.py` | `lb_ui/` | CLI functionality |
| `test_component_installability.py` | `cross_cutting/` | Multi-module concern |
| `test_data_handler.py` | `lb_analytics/` | Data handling |
| `test_env_utils.py` | `lb_common/` | Common utility |
| `test_events.py` | `lb_common/` | Event system |
| `test_grafana_client.py` | `lb_provisioner/` | Grafana integration |
| `test_interactive_selection.py` | `lb_ui/` | UI component |
| `test_jsonl_handler.py` | `lb_common/` | Common utility |
| `test_log_schema.py` | `lb_common/` | Logging |
| `test_loki_handler.py` | `lb_common/` | Logging |
| `test_plugin_export_csv.py` | `lb_plugins/` | Plugin export |
| `test_system_info.py` | `lb_runner/services/` | System info service |

## Success Criteria

1. `tests/unit/common/` directory no longer exists (or only contains `__init__.py` if required)
2. All tests pass after relocation
3. Each test file is in a directory matching its source module
4. CI pipelines updated and passing

## Risk Assessment

- **Low risk**: File moves preserve git history
- **Low risk**: No code changes, only file locations

## Dependencies

- Execute after ISSUE-002 (plugin tests) and ISSUE-003 (controller tests)
- This is the final cleanup step for the fragmentation work

## References

- CLAUDE.md: Test Organization section
- ANALYSIS.md Section 5: Test Suite Fragmentation
