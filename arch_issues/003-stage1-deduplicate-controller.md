# Issue 003: [Stage 1] Deduplicate Controller Logic

## Context
There is 84% code duplication between `ProcessStopController` and `PlaybookProcessRunner` in `lb_controller/adapters/ansible_helpers.py`. Both classes handle process lifecycles (interrupt, is_running, etc.) in a nearly identical way.

## Goal
Reduce code duplication to lower maintenance burden and ensure consistent bug fixes.

## Action Plan

### 1. Extract Base Class
- [ ] Create a base class `AnsibleProcessHandler` in `lb_controller/adapters/ansible_helpers.py`.
- [ ] Move common methods (`__init__`, `interrupt`, `is_running`, `clear_interrupt`) to the base class.

### 2. Refactor Subclasses
- [ ] Make `ProcessStopController` inherit from `AnsibleProcessHandler`.
- [ ] Make `PlaybookProcessRunner` inherit from `AnsibleProcessHandler`.
- [ ] Remove the duplicated code from the subclasses.

## Acceptance Criteria
- `cpd` or duplication report shows < 10% overlap between these classes.
- Existing controller tests pass.
