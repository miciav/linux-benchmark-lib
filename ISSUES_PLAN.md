# Refactoring Plan: Core Classes Decomposition

This document outlines the tasks required to address the "High Complexity in Core Classes" weakness identified in `ANALYSIS.md`.

## Issue 1: Extract `TestAttemptExecutor` from `LocalRunner`

**Title:** Refactor: Extract single test execution logic into `TestAttemptExecutor`

**Priority:** High
**Component:** lb_runner

**Description:**
The `LocalRunner` class currently handles both the orchestration of the entire benchmark suite and the low-level lifecycle of a single test repetition (setup, execution, teardown, metrics collection). This makes the class difficult to test and maintain.

We need to extract the logic responsible for running a single repetition into a new class called `TestAttemptExecutor`.

**Tasks:**
1.  Create a new class `TestAttemptExecutor` in `lb_runner/engine/executor.py`.
2.  Move the logic from `LocalRunner._run_single_test`, `_prepare_generator`, `_execute_generator`, and `_finalize_single_test` into this new class.
3.  The `TestAttemptExecutor` should accept:
    *   A generator instance (workload).
    *   A list of collectors.
    *   Output paths for this specific repetition.
4.  Refactor `LocalRunner` to instantiate and delegate to `TestAttemptExecutor` inside its loop.

**Acceptance Criteria:**
*   `LocalRunner` no longer contains low-level generator setup/teardown logic.
*   Unit tests for `LocalRunner` are simplified (mocking the executor).
*   New unit tests created specifically for `TestAttemptExecutor`.

---

## Issue 2: Implement `RunnerContext` to reduce parameter passing

**Title:** Refactor: Introduce `RunnerContext` to encapsulate execution scope

**Priority:** Medium
**Component:** lb_runner

**Description:**
Methods in `LocalRunner` and the proposed `TestAttemptExecutor` pass around many loosely related arguments (run_id, host_name, output_manager, stop_token) individually. This leads to "signature pollution".

We should implement a Context Object pattern to encapsulate these request-scoped dependencies.

**Tasks:**
1.  Define a `RunnerContext` (dataclass) in `lb_runner/engine/context.py`.
    *   Fields: `run_id`, `config`, `output_manager`, `log_manager`, `stop_token`.
2.  Update `LocalRunner.__init__` to initialize this context.
3.  Pass `RunnerContext` to `TestAttemptExecutor` instead of individual arguments.
4.  Update `MetricManager` to accept context where appropriate.

**Acceptance Criteria:**
*   Method signatures in `lb_runner/engine/` are significantly shorter.
*   `StopToken` is accessed via context, not passed explicitly through every stack frame.

---

## Issue 3: Decouple `MetricManager` from `LocalRunner`

**Title:** Refactor: Decouple Metric Collection orchestration

**Priority:** Medium
**Component:** lb_runner

**Description:**
Currently, `LocalRunner` directly micromanages the `MetricManager` (creating collectors, starting them, stopping them, attaching loggers). This violates SRP.

The execution flow should rely on an Observer pattern or a cleaner lifecycle hook mechanism where `MetricManager` reacts to execution phases rather than being driven procedurally by the runner's main loop.

**Tasks:**
1.  Refactor `TestAttemptExecutor` (created in Issue #1) to accept a `MetricDelegate` or similar interface.
2.  Move the `attach_event_logger` and `start_collectors` calls inside the `TestAttemptExecutor` lifecycle hooks (e.g., `__enter__` / `__exit__` or explicit `start()`/`stop()` methods).
3.  Ensure `LocalRunner` doesn't need to know about specific metric implementation details.

**Acceptance Criteria:**
*   `LocalRunner` code has zero references to `start_collectors` or `stop_collectors`.
*   Metrics are still correctly collected and persisted.

---

## Issue 4: Split `ControllerContext` into State and Services

**Title:** Refactor: Split `ControllerContext` into `RunSession` and `ControllerServices`

**Priority:** Medium
**Component:** lb_controller

**Description:**
The `ControllerContext` in `lb_controller` is a God Object holding both the mutable state of the current run (RunID, phases) and the stateless services (Ansible executor, UI Notifier). This makes mocking difficult.

**Tasks:**
1.  Extract mutable state into a new `RunSession` class (or enhance the existing `RunState`).
2.  Create a `ControllerServices` container for stateless dependencies (Executor, UI, etc.).
3.  Update `BenchmarkController` to initialize services once, and create a `RunSession` for each `run()` call.

**Acceptance Criteria:**
*   `ControllerContext` is deprecated or significantly reduced in scope.
*   The `run()` method in `BenchmarkController` explicitly creates a fresh state object for the run.
