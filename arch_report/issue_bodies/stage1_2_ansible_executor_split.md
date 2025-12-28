## Description
Split `AnsibleRunnerExecutor` into inventory, env, and process helpers to reduce complexity and improve testability.

## Plan
1. Extract inventory writing into `InventoryWriter`.
2. Extract env var assembly into `EnvBuilder`.
3. Extract subprocess execution into a `ProcessRunner` helper.
4. Preserve `RemoteExecutor` API and update unit tests.

## Acceptance Criteria
- `AnsibleRunnerExecutor` delegates to helpers and is smaller.
- Existing controller flows continue to work with no API changes.

## Risk
Medium. Adapter boundaries change.

## Evidence
- `lb_controller/adapters/ansible_runner.py:70`
- `lb_controller/adapters/ansible_runner.py:165`
