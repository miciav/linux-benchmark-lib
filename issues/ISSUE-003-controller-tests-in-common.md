# ISSUE-003: Controller-Related Tests in `tests/unit/common/`

## Summary

Several tests related to `lb_controller` functionality are located in `tests/unit/common/` instead of `tests/unit/lb_controller/`. This creates confusion about test ownership and makes module-specific test runs incomplete.

## Current State

### Misplaced Controller Tests in `common/`

```
tests/unit/common/
├── test_controller.py              # BenchmarkController tests → lb_controller
├── test_journal.py                 # Journal service tests → lb_controller
├── test_ansible_executor_signals.py # Ansible signal handling → lb_controller
├── test_setup_playbook_sync.py     # Playbook sync → lb_controller
├── test_lb_events_callback.py      # Ansible callback → lb_controller
└── test_ansible_output_formatter.py # Output formatting → lb_controller
```

### Proper Location Already Has Tests

```
tests/unit/lb_controller/
├── test_controller_runner.py
├── test_controller_state_machine.py
├── test_controller_stop.py
├── test_collect_on_stop.py
├── test_collect_playbook.py
├── test_interrupts.py
├── test_journal_sync.py
├── test_lb_event_parsing.py
├── test_lifecycle.py
├── test_logging_adapter.py
├── test_paths.py
├── test_playbook_process_runner.py
├── test_resume_metadata.py
├── test_run_catalog_service.py
├── test_run_service_plan.py
├── test_run_service_threaded.py
├── test_run_state_builders.py
├── test_services.py
├── test_session.py
└── test_stop_coordinator.py
```

## Problem Analysis

1. **Duplicate coverage potential**: `test_controller.py` in `common/` may overlap with `test_controller_runner.py` in `lb_controller/`.

2. **Incomplete module test runs**: `pytest tests/unit/lb_controller/` misses controller-related tests.

3. **Ansible tests scattered**: Ansible-related tests should be grouped together for maintainability.

## Proposed Resolution

### Target Structure

```
tests/unit/lb_controller/
├── ansible/
│   ├── test_ansible_executor_signals.py
│   ├── test_ansible_output_formatter.py
│   ├── test_lb_events_callback.py
│   └── test_setup_playbook_sync.py
├── services/
│   ├── test_journal.py
│   ├── test_journal_sync.py      # Already exists
│   └── test_run_catalog_service.py  # Already exists
├── test_controller.py            # Merged with test_controller_runner.py
└── ... (other existing files)
```

## Action Plan

### Step 1: Audit for Duplicates

Before moving, check for test overlap:

```bash
# Compare test functions
grep -h "^def test_" tests/unit/common/test_controller.py tests/unit/lb_controller/test_controller_runner.py | sort
```

**Action items:**
- If duplicate tests exist, merge and deduplicate
- If tests are complementary, consolidate into single file

**Estimated effort:** 30 minutes

### Step 2: Create Subdirectory Structure

```bash
mkdir -p tests/unit/lb_controller/ansible
mkdir -p tests/unit/lb_controller/services
touch tests/unit/lb_controller/ansible/__init__.py
touch tests/unit/lb_controller/services/__init__.py
```

**Estimated effort:** 5 minutes

### Step 3: Relocate Ansible Tests

```bash
git mv tests/unit/common/test_ansible_executor_signals.py tests/unit/lb_controller/ansible/
git mv tests/unit/common/test_ansible_output_formatter.py tests/unit/lb_controller/ansible/
git mv tests/unit/common/test_lb_events_callback.py tests/unit/lb_controller/ansible/
git mv tests/unit/common/test_setup_playbook_sync.py tests/unit/lb_controller/ansible/
```

**Estimated effort:** 10 minutes

### Step 4: Relocate Service Tests

```bash
git mv tests/unit/common/test_journal.py tests/unit/lb_controller/services/
```

**Estimated effort:** 5 minutes

### Step 5: Merge Controller Tests

```bash
# Option A: Rename and keep both (if different focus)
git mv tests/unit/common/test_controller.py tests/unit/lb_controller/test_controller_legacy.py

# Option B: Merge into existing file
# Manually merge content into test_controller_runner.py
```

**Decision required:** Review content to decide merge strategy.

**Estimated effort:** 45 minutes

### Step 6: Update Markers

Ensure consistent markers:

```python
# In ansible test files
pytestmark = [pytest.mark.unit_controller, pytest.mark.unit_controller_ansible]

# In service test files
pytestmark = [pytest.mark.unit_controller, pytest.mark.unit_controller_services]
```

**Estimated effort:** 20 minutes

### Step 7: Verify and Clean Up

```bash
# Verify all controller tests discoverable
pytest tests/unit/lb_controller/ --collect-only

# Run full test suite
pytest tests/unit/lb_controller/ -v
```

**Estimated effort:** 15 minutes

## Files to Relocate

| Current Path | New Path | Notes |
|--------------|----------|-------|
| `tests/unit/common/test_controller.py` | `tests/unit/lb_controller/test_controller.py` | Merge with existing if overlap |
| `tests/unit/common/test_journal.py` | `tests/unit/lb_controller/services/test_journal.py` | Service layer test |
| `tests/unit/common/test_ansible_executor_signals.py` | `tests/unit/lb_controller/ansible/test_ansible_executor_signals.py` | Ansible integration |
| `tests/unit/common/test_setup_playbook_sync.py` | `tests/unit/lb_controller/ansible/test_setup_playbook_sync.py` | Playbook handling |
| `tests/unit/common/test_lb_events_callback.py` | `tests/unit/lb_controller/ansible/test_lb_events_callback.py` | Callback plugin tests |
| `tests/unit/common/test_ansible_output_formatter.py` | `tests/unit/lb_controller/ansible/test_ansible_output_formatter.py` | Output formatting |

## Success Criteria

1. `pytest tests/unit/lb_controller/ --collect-only` discovers all controller tests
2. `tests/unit/common/` contains no controller-related tests
3. No duplicate test functions after merge
4. All tests pass after relocation

## Risk Assessment

- **Medium risk**: Potential duplicate tests require manual review
- **Low risk**: File moves preserve git history

## Dependencies

- Review for duplicates before proceeding (Step 1 is blocking)

## References

- CLAUDE.md: Test Organization section
- ANALYSIS.md Section 5: Test Suite Fragmentation
