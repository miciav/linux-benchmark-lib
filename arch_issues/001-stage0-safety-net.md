# Issue 001: [Stage 0] Safety Net - Characterization Tests

## Context
We are about to refactor `lb_app.services.RunService` and `lb_app.services.ConfigService`, which are core components. Currently, `RunService` has high complexity and interacts with many other components. To prevent regressions, we need to "pin" the current behavior with characterization tests.

## Goal
Establish a baseline of tests that verify the *current* behavior of `RunService.run_benchmark` and configuration parsing, even if that behavior is imperfect. This allows us to refactor with confidence.

## Action Plan

### 1. RunService Characterization
- [ ] Create `tests/inter_char/test_run_service_char.py`.
- [ ] Write a test that mocks `BenchmarkController` and `RunnerRegistry`.
- [ ] Invoke `RunService.run_benchmark` with a standard configuration (e.g., `stress_ng`).
- [ ] Assert that the correct controller methods are called (spying).
- [ ] Assert that the correct output events are generated.

### 2. Config Parsing Snapshot
- [ ] Create a script or test that loads `lb_config` (default) and dumps the parsed object to a JSON/text snapshot.
- [ ] Store this snapshot in `tests/snapshots/`.
- [ ] Add a test that loads the config and compares it byte-for-byte with the snapshot.

## Acceptance Criteria
- `pytest tests/inter_char/` passes.
- A snapshot file exists for the default configuration.
