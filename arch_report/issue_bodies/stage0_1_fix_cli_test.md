## Description
Fix the failing `test_run_command_exists` and align its setup with the current CLI workload selection behavior so the unit UI test suite is green.

## Plan
1. Reproduce `tests/test_cli.py::test_run_command_exists` failure.
2. Align test setup with CLI behavior in `lb_ui/cli/commands/run.py`.
3. Ensure at least one enabled workload exists in the test config, or update the fixture to mirror defaults.
4. Re-run unit UI tests to confirm the fix.

## Acceptance Criteria
- `tests/test_cli.py::test_run_command_exists` passes consistently.
- `uv run pytest -m unit_ui` is green (or the equivalent CI marker run).

## Risk
Low. Test-only adjustments.

## Evidence
- `tests/test_cli.py:551`
- `lb_ui/cli/commands/run.py:158`
