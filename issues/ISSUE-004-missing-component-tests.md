# ISSUE-004: Missing Tests for Extracted Engine Components

## Summary

Recent refactoring has extracted several components from `LocalRunner`, but dedicated test files for these components are either missing or incomplete. This creates a testing gap where new components are only tested indirectly through integration tests.

## Current State

### Engine Components and Test Coverage

| Component | Source File | Test File | Coverage Status |
|-----------|-------------|-----------|-----------------|
| `RunnerContext` | `lb_runner/engine/context.py` | ❌ None | **Missing** |
| `RepetitionExecutor` | `lb_runner/engine/executor.py` | ✅ `test_executor.py` | Partial |
| `ProgressEmitter` | `lb_runner/engine/progress.py` | ❌ None | **Missing** |
| `RunPlanner` | `lb_runner/engine/planning.py` | ⚠️ `test_local_runner_helpers.py` | Misnamed |
| `RunScope` | `lb_runner/engine/run_scope.py` | ❌ None | **Missing** |
| `StopContext` | `lb_runner/engine/stop_context.py` | ✅ `test_stop_context.py` | New |
| `StopToken` | `lb_runner/engine/stop_token.py` | ❌ None | **Missing** |
| `MetricManager` | `lb_runner/engine/metrics.py` | ⚠️ Indirect only | **Incomplete** |

### Service Components and Test Coverage

| Component | Source File | Test File | Coverage Status |
|-----------|-------------|-----------|-----------------|
| `ResultPersister` | `lb_runner/services/result_persister.py` | ❌ None | **Missing** |
| `RunnerLogManager` | `lb_runner/services/runner_log_manager.py` | ❌ None | **Missing** |
| `RunnerOutputManager` | `lb_runner/services/runner_output_manager.py` | ❌ None | **Missing** |
| `CollectorCoordinator` | `lb_runner/services/collector_coordinator.py` | ⚠️ Indirect | **Incomplete** |
| `AsyncLocalRunner` | `lb_runner/services/async_localrunner.py` | ❌ None | **Missing** |

## Problem Analysis

1. **Refactoring debt**: Components extracted from `LocalRunner` don't have matching test files.

2. **Integration-only testing**: New components are tested only through `LocalRunner` tests, making failures hard to isolate.

3. **Naming mismatch**: `test_local_runner_helpers.py` tests `RunPlanner`, but the name doesn't reflect this.

4. **New files without tests**: `stop_context.py` was recently added (visible in git status) but test coverage needs verification.

## Proposed Resolution

### Priority 1: Critical Path Components (High)

These components are in the main execution path and need immediate test coverage:

```
tests/unit/lb_runner/engine/
├── test_runner_context.py      # NEW
├── test_repetition_executor.py # EXISTS (verify completeness)
├── test_progress_emitter.py    # NEW
└── test_run_planner.py         # RENAME from test_local_runner_helpers.py
```

### Priority 2: Supporting Components (Medium)

```
tests/unit/lb_runner/engine/
├── test_run_scope.py           # NEW
├── test_stop_token.py          # NEW
├── test_stop_context.py        # EXISTS (verify)
└── test_metric_manager.py      # NEW (extract from test_collect_metrics.py)
```

### Priority 3: Service Layer (Lower)

```
tests/unit/lb_runner/services/
├── test_result_persister.py    # NEW
├── test_runner_log_manager.py  # NEW
├── test_runner_output_manager.py  # NEW
├── test_collector_coordinator.py  # NEW
└── test_async_localrunner.py   # NEW
```

## Action Plan

### Step 1: Create Directory Structure

```bash
mkdir -p tests/unit/lb_runner/engine
mkdir -p tests/unit/lb_runner/services
touch tests/unit/lb_runner/engine/__init__.py
touch tests/unit/lb_runner/services/__init__.py
```

**Estimated effort:** 5 minutes

### Step 2: Rename Existing Misnamed Tests

```bash
git mv tests/unit/lb_runner/test_local_runner_helpers.py \
       tests/unit/lb_runner/engine/test_run_planner.py
```

Update imports in the file:
```python
# Update any LocalRunner-specific imports to RunPlanner
from lb_runner.engine.planning import RunPlanner
```

**Estimated effort:** 15 minutes

### Step 3: Create RunnerContext Tests

```python
# tests/unit/lb_runner/engine/test_runner_context.py
"""Unit tests for RunnerContext initialization and attribute access."""

import pytest
from unittest.mock import MagicMock
from lb_runner.engine.context import RunnerContext

pytestmark = pytest.mark.unit_runner


class TestRunnerContextInit:
    def test_requires_run_id(self):
        """RunnerContext must have a run_id."""
        with pytest.raises(TypeError):
            RunnerContext(config=MagicMock())

    def test_stores_config(self):
        """Config should be accessible."""
        config = MagicMock()
        ctx = RunnerContext(run_id="test", config=config)
        assert ctx.config is config

    def test_optional_stop_token(self):
        """StopToken is optional and defaults to None."""
        ctx = RunnerContext(run_id="test", config=MagicMock())
        assert ctx.stop_token is None


class TestRunnerContextManagers:
    def test_output_manager_access(self):
        """OutputManager should be accessible."""
        output_mgr = MagicMock()
        ctx = RunnerContext(
            run_id="test",
            config=MagicMock(),
            output_manager=output_mgr
        )
        assert ctx.output_manager is output_mgr
```

**Estimated effort:** 1 hour

### Step 4: Create ProgressEmitter Tests

```python
# tests/unit/lb_runner/engine/test_progress_emitter.py
"""Unit tests for ProgressEmitter event formatting."""

import pytest
from lb_runner.engine.progress import ProgressEmitter

pytestmark = pytest.mark.unit_runner


class TestProgressEmitterFormat:
    def test_emit_running_status(self):
        """Emit should format running status correctly."""
        emitter = ProgressEmitter()
        event = emitter.format_event("workload", 1, 3, "running")
        assert event["workload"] == "workload"
        assert event["repetition"] == 1
        assert event["status"] == "running"

    def test_emit_done_includes_message(self):
        """Done status should include optional message."""
        emitter = ProgressEmitter()
        event = emitter.format_event("w", 1, 1, "done", message="OK")
        assert event["message"] == "OK"

    def test_emit_failed_includes_error_type(self):
        """Failed status should include error type."""
        emitter = ProgressEmitter()
        event = emitter.format_event(
            "w", 1, 1, "failed",
            error_type="WorkloadError",
            error_context={"cmd": "stress-ng"}
        )
        assert event["error_type"] == "WorkloadError"
```

**Estimated effort:** 1 hour

### Step 5: Create StopToken Tests

```python
# tests/unit/lb_runner/engine/test_stop_token.py
"""Unit tests for StopToken signaling."""

import pytest
from lb_runner.engine.stop_token import StopToken

pytestmark = pytest.mark.unit_runner


class TestStopTokenSignal:
    def test_initial_state_not_stopped(self):
        """Token should not be stopped initially."""
        token = StopToken()
        assert token.should_stop() is False

    def test_request_stop_sets_flag(self):
        """request_stop should set the stop flag."""
        token = StopToken()
        token.request_stop()
        assert token.should_stop() is True

    def test_reset_clears_flag(self):
        """reset should clear the stop flag."""
        token = StopToken()
        token.request_stop()
        token.reset()
        assert token.should_stop() is False
```

**Estimated effort:** 30 minutes

### Step 6: Create MetricManager Tests

Extract and expand from `test_collect_metrics.py`:

```python
# tests/unit/lb_runner/engine/test_metric_manager.py
"""Unit tests for MetricManager collector coordination."""

import pytest
from unittest.mock import MagicMock
from lb_runner.engine.metrics import MetricManager

pytestmark = pytest.mark.unit_runner


class TestMetricManagerLifecycle:
    def test_start_collectors_calls_each(self):
        """start_collectors should call start() on each collector."""
        mgr = MetricManager(config=MagicMock())
        c1, c2 = MagicMock(), MagicMock()
        mgr.start_collectors([c1, c2])
        c1.start.assert_called_once()
        c2.start.assert_called_once()

    def test_stop_collectors_handles_exceptions(self):
        """stop_collectors should not propagate collector errors."""
        mgr = MetricManager(config=MagicMock())
        bad = MagicMock()
        bad.stop.side_effect = RuntimeError("boom")
        good = MagicMock()
        mgr.stop_collectors([bad, good])
        good.stop.assert_called_once()
```

**Estimated effort:** 1 hour

### Step 7: Reorganize Existing Test Files

```bash
# Move engine-specific tests to engine subdirectory
git mv tests/unit/lb_runner/test_executor.py tests/unit/lb_runner/engine/
git mv tests/unit/lb_runner/test_stop_context.py tests/unit/lb_runner/engine/

# Move service tests to services subdirectory
git mv tests/unit/lb_runner/test_collect_metrics.py tests/unit/lb_runner/services/
```

**Estimated effort:** 15 minutes

### Step 8: Update conftest and Markers

```python
# tests/unit/lb_runner/conftest.py
import pytest

# Register fixtures available to all lb_runner tests
@pytest.fixture
def mock_config():
    from unittest.mock import MagicMock
    config = MagicMock()
    config.warmup_seconds = 0
    config.cooldown_seconds = 0
    config.output_dir = "/tmp/test"
    return config
```

**Estimated effort:** 30 minutes

## Success Criteria

1. Each source file in `lb_runner/engine/` has a matching test file
2. Each source file in `lb_runner/services/` has a matching test file
3. Test file names match source file names
4. All new tests pass
5. Coverage report shows improvement in engine/services modules

## Verification Commands

```bash
# Check all components have tests
for f in lb_runner/engine/*.py; do
  base=$(basename "$f" .py)
  test_file="tests/unit/lb_runner/engine/test_${base}.py"
  [ -f "$test_file" ] || echo "Missing: $test_file"
done

# Run new tests
pytest tests/unit/lb_runner/engine/ tests/unit/lb_runner/services/ -v

# Coverage check
pytest --cov=lb_runner.engine --cov=lb_runner.services tests/unit/lb_runner/
```

## Dependencies

- ISSUE-001: LocalRunner test consolidation (can proceed in parallel)
- Requires reading source files to understand component interfaces

## References

- ANALYSIS.md Section 1: High Complexity in Core Classes
- ANALYSIS.md Section 5: Test Suite Fragmentation
