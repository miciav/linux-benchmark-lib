## Description
Add characterization tests for controller and runner orchestration to create a safety net before refactors.

## Plan
1. Add a fake `RemoteExecutor` that records playbook calls and returns deterministic `ExecutionResult`.
2. Build a minimal `BenchmarkConfig` with one host and one workload.
3. Assert journal behavior, run phases, and summary fields are stable.
4. Add a fake generator and collector for `LocalRunner` and assert output structure.

## Acceptance Criteria
- New unit tests cover controller and runner orchestration paths without requiring Ansible/Docker.
- Tests pass locally with `uv run pytest tests/ -m 'unit_controller or unit_runner'`.

## Risk
Low. Test additions only.

## Evidence
- `lb_controller/engine/controller.py:72`
- `lb_runner/engine/runner.py:59`
