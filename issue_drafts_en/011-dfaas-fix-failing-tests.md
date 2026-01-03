# DFAAS-FIX-1: Fix failing unit tests

## Context
The DFaaS plugin has 2 failing unit tests due to outdated test expectations that don't match the actual implementation.

## Goal
Fix the failing tests to restore CI green status.

## Scope
- Update test assertions to match actual implementation
- No changes to production code

## Non-scope
- Adding new tests
- Refactoring existing tests

## Current Failures

### Test 1: `test_dfaas_readme_has_required_sections`
**File**: `tests/unit/lb_plugins/test_dfaas_docs.py:19`
**Error**: Test expects sections that don't exist in README
```python
for section in [
    "## Architecture",      # Missing
    "## Prerequisites",     # Missing
    "## Setup steps",       # Missing
    "## Run flow",          # Missing
    "## Outputs",           # Missing
    "## Troubleshooting",   # Missing
]:
    assert section in readme
```
**Root cause**: README was written with different section headers than the test expects.

### Test 2: `test_setup_k6_playbook_installs_k6`
**File**: `tests/unit/lb_plugins/test_dfaas_playbooks.py:21`
**Error**: Test expects apt-based k6 installation
```python
assert any(
    task.get("ansible.builtin.apt", {}).get("name") == "k6"
    for task in tasks
)
```
**Root cause**: Playbook uses shell-based installation via `gpg` + `apt-get`, not `ansible.builtin.apt`.

## Partial Objectives + Tests

### Objective 1: Fix README section test
**Solution**: Update test to check for actual README sections or update README (covered by issue 012).
**Option A** (minimal): Change test assertions to match current README headers
**Option B** (preferred): Keep test as-is and fix README in issue 012

**Tests**:
- `uv run pytest tests/unit/lb_plugins/test_dfaas_docs.py -v` passes

### Objective 2: Fix playbook installation test
**Solution**: Update test to check for shell-based k6 installation pattern.
```python
# New assertion
assert any(
    "k6" in str(task.get("ansible.builtin.shell", ""))
    or "gpg.k6.io" in str(task.get("ansible.builtin.shell", ""))
    for task in tasks
)
```

**Tests**:
- `uv run pytest tests/unit/lb_plugins/test_dfaas_playbooks.py -v` passes

## Acceptance Criteria
- [ ] All 17 DFaaS unit tests pass
- [ ] No test logic changes that would hide real bugs
- [ ] Test intent preserved (verify k6 installation, verify README sections)

## Files to Modify
- `tests/unit/lb_plugins/test_dfaas_docs.py`
- `tests/unit/lb_plugins/test_dfaas_playbooks.py`

## Dependencies
- None (can start immediately)
- Blocks: 012 (README completion should align with test expectations)

## Effort
~1 hour

