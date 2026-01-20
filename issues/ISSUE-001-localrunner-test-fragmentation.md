# ISSUE-001: LocalRunner Test Suite Fragmentation

## Summary

The `LocalRunner` tests are fragmented across 5 files without a clear organizational principle. This fragmentation is symptomatic of the `LocalRunner` class being a "God Class" with too many responsibilities.

## Current State

| File | Purpose | Line Count | Tests |
|------|---------|------------|-------|
| `test_local_runner_unit.py` | DI, log handlers, result merging | ~90 | 3 |
| `test_local_runner_failures.py` | Edge cases, error handling | ~140 | 4 |
| `test_local_runner_progress.py` | Progress event emission | ~100 | 2 |
| `test_local_runner_helpers.py` | RunPlanner, merge_results | ~75 | 4 |
| `test_local_runner_characterization.py` | Execution flow golden path | ~95 | 1 |

**Total: ~500 lines across 5 files testing the same class**

## Problem Analysis

1. **Symptom, not cause**: The fragmentation reflects `LocalRunner`'s multiple responsibilities:
   - Run planning and scope management
   - Execution loop orchestration
   - Result persistence and merging
   - Progress event emission
   - Metric collection coordination

2. **Test naming inconsistency**: Files like `test_local_runner_helpers.py` actually test `RunPlanner` (a separate class), not `LocalRunner`.

3. **Unclear test categories**:
   - "characterization" vs "unit" distinction is unclear
   - "failures" could be split into error-handling vs edge-cases

## Proposed Resolution

### Phase 1: Align Tests with Existing Components

As refactoring extracts responsibilities from `LocalRunner`, align test files with the new components:

| New Test File | Source Component | Migration From |
|---------------|------------------|----------------|
| `test_run_planner.py` | `lb_runner/engine/planning.py` | `test_local_runner_helpers.py` |
| `test_repetition_executor.py` | `lb_runner/engine/executor.py` | Partial from `test_local_runner_progress.py` |
| `test_runner_context.py` | `lb_runner/engine/context.py` | New tests needed |
| `test_metric_manager.py` | `lb_runner/engine/metrics.py` | `test_collect_metrics.py` (partial) |
| `test_result_persister.py` | `lb_runner/services/result_persister.py` | `test_local_runner_unit.py` (merge tests) |

### Phase 2: Consolidate Remaining LocalRunner Tests

After extraction, `LocalRunner` should only orchestrate:

```
tests/unit/lb_runner/
├── test_local_runner.py         # Consolidated: DI, orchestration, lifecycle
├── test_run_planner.py          # Extracted from helpers
├── test_repetition_executor.py  # Execution per-rep logic
├── test_runner_context.py       # Context/scope management
├── test_metric_manager.py       # Collector coordination
└── test_result_persister.py     # Result storage
```

### Phase 3: Test Category Clarification

Define clear categories via pytest markers:

```python
# conftest.py additions
pytest.mark.unit_runner_orchestration  # LocalRunner orchestration
pytest.mark.unit_runner_execution      # Execution loop logic
pytest.mark.unit_runner_planning       # RunPlanner, scope
pytest.mark.unit_runner_metrics        # Collectors, MetricManager
pytest.mark.unit_runner_persistence    # Results, storage
```

## Action Plan

### Step 1: Rename and Relocate (Low Risk)

```bash
# Rename helpers to match actual tested class
git mv tests/unit/lb_runner/test_local_runner_helpers.py \
       tests/unit/lb_runner/test_run_planner.py
```

**Files affected:**
- `tests/unit/lb_runner/test_local_runner_helpers.py` → `test_run_planner.py`

**Estimated effort:** 15 minutes

### Step 2: Consolidate Core LocalRunner Tests

Merge into single `test_local_runner.py`:
- `test_local_runner_unit.py` → Core DI and lifecycle tests
- `test_local_runner_characterization.py` → Golden-path integration test (keep separate or merge)
- `test_local_runner_failures.py` → Error handling section

**Decision point:** Keep characterization tests separate if they serve as regression tests for refactoring.

**Estimated effort:** 1 hour

### Step 3: Create Missing Component Tests

Components currently lacking dedicated tests:
- `lb_runner/engine/context.py` - `RunnerContext`
- `lb_runner/engine/progress.py` - `ProgressEmitter`
- `lb_runner/engine/run_scope.py` - Scope management

Create test stubs:
```python
# tests/unit/lb_runner/test_runner_context.py
"""Unit tests for RunnerContext initialization and access."""

# tests/unit/lb_runner/test_progress_emitter.py
"""Unit tests for ProgressEmitter event formatting."""
```

**Estimated effort:** 2-3 hours

### Step 4: Update Test Markers

Add granular markers to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
markers = [
    "unit_runner: all runner unit tests",
    "unit_runner_core: LocalRunner orchestration",
    "unit_runner_execution: execution loop tests",
    "unit_runner_planning: RunPlanner tests",
    "unit_runner_metrics: metric collection tests",
]
```

**Estimated effort:** 30 minutes

## Success Criteria

1. Each test file tests exactly one component
2. Test file names match source file names (e.g., `test_run_planner.py` ↔ `planning.py`)
3. No more than 200 lines per test file (split if larger)
4. All tests run with: `pytest -m unit_runner`
5. Component-specific tests: `pytest -m unit_runner_planning`

## Dependencies

- Depends on ISSUE-002 (ANALYSIS.md Section 1) for `LocalRunner` refactoring
- Can proceed with Step 1 immediately (rename only)

## References

- ANALYSIS.md Section 1: High Complexity in Core Classes
- ANALYSIS.md Section 5: Test Suite Fragmentation
