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

---

## Issue 5: Extract `ControllerServices` container

**Title:** Refactor: Extract `ControllerServices` container

**Priority:** Medium
**Component:** lb_controller

**Description:**
The `ControllerContext` currently acts as a catch-all for both services and state. We need to separate the stateless infrastructure dependencies into a dedicated container.

**Tasks:**
1.  Create a `ControllerServices` class in `lb_controller/services/services.py`.
2.  Move `BenchmarkConfig`, `RemoteExecutor`, `UINotifier` (or OutputFormatter), and `StopToken` fields from `ControllerContext` to `ControllerServices`.
3.  Ensure `ControllerServices` is immutable after initialization (or effectively so).

**Acceptance Criteria:**
*   `ControllerServices` exists and holds the specified dependencies.
*   Unit tests verify correct initialization.

---

## Issue 6: Refactor `RunState` into `RunSession`

**Title:** Refactor: Enhance `RunState` into `RunSession`

**Priority:** Medium
**Component:** lb_controller

**Description:**
We need to encapsulate the mutable state of a specific run (which includes the state machine and stop coordinator) separate from the static services.

**Tasks:**
1.  Rename or wrap `RunState` into a new class `RunSession` in `lb_controller/engine/session.py`.
2.  Move `ControllerStateMachine` and `StopCoordinator` ownership from `ControllerContext` to `RunSession`.
3.  Implement methods on `RunSession` to handle state transitions (moving logic like `_transition` and `_arm_stop` out of `ControllerContext`).

**Acceptance Criteria:**
*   `RunSession` encapsulates all dynamic state for a single run.
*   State transitions are managed via methods on `RunSession`.

---

## Issue 7: Refactor `BenchmarkController` to use Services and Session

**Title:** Refactor: Update `BenchmarkController` to use Services and Session

**Priority:** Medium
**Component:** lb_controller

**Description:**
Update the main controller class to utilize the new decoupled components instead of the monolithic `ControllerContext`.

**Tasks:**
1.  Update `BenchmarkController.__init__` to initialize `ControllerServices`.
2.  Update `BenchmarkController.run` to create a new `RunSession` for each execution.
3.  Refactor helper functions (like `run_global_setup` and `workload_runner`) to accept `ControllerServices` and `RunSession` instead of `ControllerContext`.
4.  Deprecate or remove the old `ControllerContext`.

**Acceptance Criteria:**
*   `BenchmarkController` instantiates services once and session per run.
*   The code no longer relies on the monolithic `ControllerContext` for passing dependencies.