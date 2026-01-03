# Ctrl+C, Stop Coordination, and Teardown Authority

## Thread and Component Model

- **UI/main thread** drives the dashboard and installs a `SigintDoublePressHandler` through `lb_app.services.run_service.RunService`. It never exits on the first Ctrl+C while the controller thread is active; instead it posts notifications to a queue that the main loop drains.
- **Controller worker thread** (`ControllerRunner` via `lb_controller.async_api`) owns orchestration and transitions a shared `ControllerStateMachine`.
- **AnsibleRunnerExecutor** executes playbooks in subprocesses and exposes `interrupt()` + `is_running` for safe cancellation.
- **lb_runner** emits progress/stop events; the controller consumes them for stop confirmation.
- **lb_provisioner** is invoked from the CLI (`lb_ui`); cleanup is gated by controller state (`cleanup_allowed`).

## State Machine (phase-aware and monotonic)

States: `INIT -> RUNNING_GLOBAL_SETUP -> RUNNING_WORKLOADS -> RUNNING_GLOBAL_TEARDOWN -> FINISHED`

Stop path: `... -> STOP_ARMED -> STOPPING_INTERRUPT_SETUP | STOPPING_WAIT_RUNNERS -> STOPPING_TEARDOWN -> ABORTED`

Failure path: any state -> `STOP_FAILED` (stop protocol timeout) or `FAILED` (unexpected error)

Rules:

- Transitions are validated and thread-safe.
- Cleanup is allowed only in `FINISHED` or `ABORTED`.
- Stop arming is idempotent; terminal states are immutable.

## Ctrl+C Semantics

- **1st Ctrl+C:** warn in the UI log area: \"Press Ctrl+C again to stop the execution\". No stop is requested.
- **2nd Ctrl+C:** enqueue a stop request; `ControllerRunner.arm_stop` (from `lb_controller.async_api`) transitions to `STOP_ARMED` and raises the shared `StopToken`.
- Further Ctrl+C while stopping are ignored until the controller finishes; process exit is not triggered by the UI.

## Phase-aware Stop Handling

- **GLOBAL_SETUP:** `stop_token` triggers `STOPPING_INTERRUPT_SETUP`; the running playbook is interrupted via `AnsibleRunnerExecutor.interrupt`. Controller proceeds to `STOPPING_TEARDOWN` before finishing in `ABORTED`.
- **WORKLOAD_RUN:** `STOPPING_WAIT_RUNNERS` kicks off the distributed stop protocol. Runners must confirm via events keyed by `run_id`; on success the controller enters `STOPPING_TEARDOWN`, else `STOP_FAILED`.
- **GLOBAL_TEARDOWN:** stop arms `STOPPING_INTERRUPT_TEARDOWN` and interrupts the teardown playbook; outcome is `ABORTED` or `STOP_FAILED`.

## AnsibleRunner Interrupt Semantics

- Single execution path through `AnsibleRunnerExecutor.run_playbook`.
- Cancellable calls honor `StopToken` and a local interrupt flag; `interrupt()` is idempotent and terminates the subprocess when present.
- `is_running` exposes whether a playbook is in-flight for diagnostics and stop decisions.

## Provisioning Lifecycle Integration

- `RunExecutionSummary.cleanup_allowed` reflects `ControllerStateMachine.allows_cleanup`.
- `lb_ui` only destroys provisioned nodes when `cleanup_allowed` is `True`; otherwise nodes are preserved for inspection.
