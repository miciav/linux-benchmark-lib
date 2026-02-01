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

---

# Refactoring Plan: Error Handling Improvements

This document outlines the tasks required to address the "Generic Error Handling" weakness identified in `ANALYSIS.md`.

## Issue 8: Define shared error taxonomy

**Title:** Refactor: Introduce a shared error taxonomy and helpers

**Priority:** Medium
**Component:** lb_common

**Description:**
The codebase uses broad `except Exception` blocks across multiple layers. We need a shared error taxonomy so failures can be categorized, logged consistently, and propagated with context.

**Tasks:**
1.  Add `lb_common/errors.py` with a base `LBError` and context payload.
2.  Define typed subclasses (e.g., `WorkloadError`, `MetricCollectionError`, `ResultPersistenceError`, `OutputParseError`, `RemoteExecutionError`, `ConfigurationError`).
3.  Provide a helper to wrap exceptions with context and preserve the original cause.

**Acceptance Criteria:**
*   `lb_common/errors.py` exists and is imported by core modules.
*   Typed errors carry context and the original exception chain.

---

## Issue 9: Refactor runner/executor error handling

**Title:** Refactor: Handle typed errors explicitly in runner execution loops

**Priority:** High
**Component:** lb_runner

**Description:**
Runner execution loops catch generic exceptions and continue, which can hide critical failures. We need explicit handling for cancellation and recoverable errors, with full stack traces for unexpected failures.

**Tasks:**
1.  Update `lb_runner/engine/runner.py` and `lb_runner/engine/executor.py` to catch `StopRequested` and `LBError` separately.
2.  Replace broad catches with `logger.exception` plus re-raise, or wrap into `LBError` with context.
3.  Ensure result records and progress events include the error type and message on failure.

**Acceptance Criteria:**
*   Unexpected exceptions produce stack traces and fail the affected repetition or run.
*   Recoverable errors are handled explicitly and reported consistently.

---

## Issue 10: Wrap collector and plugin failures in typed errors

**Title:** Refactor: Convert collector/generator failures into typed errors

**Priority:** Medium
**Component:** lb_runner, lb_plugins

**Description:**
Collectors and generators currently swallow or re-raise raw exceptions, which makes failures hard to categorize. We should wrap external tool failures and plugin errors into typed exceptions with context.

**Tasks:**
1.  Update `lb_runner/metric_collectors/_base_collector.py` to wrap failures into `MetricCollectionError`.
2.  Update `lb_plugins/base_generator.py` to wrap execution/parse failures into `WorkloadError`.
3.  Add context fields (workload name, repetition, collector name, command/exit code where applicable).

**Acceptance Criteria:**
*   Collector and generator failures bubble up as typed errors.
*   Error context is available for reporting and debugging.

---

## Issue 11: Propagate error types through controller/app reporting

**Title:** Refactor: Surface typed errors in journals and UI reporting

**Priority:** Medium
**Component:** lb_controller, lb_app

**Description:**
Error classification should reach the orchestration and reporting layers so users can distinguish failures and recoveries without digging through logs.

**Tasks:**
1.  Update run journal entries to include error type and context.
2.  Update `lb_app` event and output services to display typed errors consistently.
3.  Map error types to run status and exit codes for CLI flows.

**Acceptance Criteria:**
*   Journals and UI outputs include the error type and relevant context.
*   Run status/exit codes reflect the error category.

---

## Issue 12: Add tests for error classification and propagation

**Title:** Test: Cover typed error handling across runner and orchestration

**Priority:** Medium
**Component:** tests

**Description:**
We need tests that assert error classification and propagation behave as expected in both runner and app/controller flows.

**Tasks:**
1.  Add unit tests for runner/executor to validate `StopRequested` vs `LBError` handling.
2.  Add tests for collector/generator error wrapping.
3.  Add a small integration test to ensure the run pipeline records error types in outputs/journals.

**Acceptance Criteria:**
*   Tests cover the main error-handling paths and pass consistently.

---

# Refactoring Plan: Stop Token Intrusiveness

This document outlines the tasks required to address the "Stop Token Intrusiveness" weakness identified in `ANALYSIS.md`.

## Issue 13: Introduce a stop context helper

**Title:** Refactor: Add a context-scoped stop token helper

**Priority:** Low
**Component:** lb_runner

**Description:**
StopToken is passed through multiple layers just to reach the execution loop. Introduce a scoped helper using `contextvars` so consumers can fetch the active token without signature threading.

**Tasks:**
1.  Add `lb_runner/engine/stop_context.py` with a `ContextVar` and helpers (`set_stop_token`, `get_stop_token`, `clear_stop_token`).
2.  Provide a lightweight wrapper to read from the context while preserving access to an explicit StopToken when one is provided.

**Acceptance Criteria:**
*   Stop context helper exists and is importable.
*   No behavior changes yet; helper is ready for integration.

---

## Issue 14: Wire stop context into runner/executor flow

**Title:** Refactor: Use stop context in runner/executor paths

**Priority:** Low
**Component:** lb_runner

**Description:**
Runner/executor logic should use the stop context rather than threading StopToken through helper calls.

**Tasks:**
1.  Update `LocalRunner` to set the stop context at run start and clear it at run end.
2.  Update `lb_runner/engine/execution.py` helpers to access the stop token via context instead of explicit parameters where possible.
3.  Keep compatibility with explicit token parameters during the transition.

**Acceptance Criteria:**
*   StopToken no longer needs to be passed to internal helper calls in the runner.
*   Stop checks still function correctly in local and async runner flows.

---

## Issue 15: Update entrypoints and adapters to populate stop context

**Title:** Refactor: Populate stop context in entrypoints/adapters

**Priority:** Low
**Component:** lb_runner, lb_app, lb_controller

**Description:**
Ensure the stop context is correctly populated for both local runs and remote orchestration so cancellation remains consistent.

**Tasks:**
1.  Update `lb_runner/services/async_localrunner.py` to set the stop context for the run lifetime.
2.  Update relevant controller/app adapters that rely on StopToken for cancellation to use the context helper.
3.  Ensure explicit StopToken use continues to work as a fallback.

**Acceptance Criteria:**
*   Stop context is active in local and async flows.
*   No behavioral regressions in stop handling.

---

## Issue 16: Add tests for stop context behavior

**Title:** Test: Verify stop context behavior across runs

**Priority:** Low
**Component:** tests

**Description:**
Add tests to ensure stop context is set and cleared properly and that cancellation still works.

**Tasks:**
1.  Add unit tests for `stop_context` helpers.
2.  Add a runner test to confirm context is cleared between runs.
3.  Add a small integration test that simulates stop signals via context.

**Acceptance Criteria:**
*   Tests cover stop context lifecycle and cancellation behavior.
