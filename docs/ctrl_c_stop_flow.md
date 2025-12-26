# Ctrl+C Isolation, State Machine, and Stop Flow

## Why Ansible Was Getting Killed

- Previously `ansible-playbook` was spawned in the same process group as the UI, so the first Ctrl+C delivered SIGINT directly to the child process, aborting setup and marking the controller as failed.
- Consequence: the dashboard exited immediately, setup stopped mid-flight, and the controller could not drive a coordinated stop/teardown.

## What Changed (Isolation)

- Ansible subprocesses now run in their own session (`start_new_session=True`). A Ctrl+C in the UI no longer auto-terminates Ansible; the controller remains in charge.
- `AnsibleRunnerExecutor.interrupt()` is idempotent and clears active process metadata; `is_running` reports in-flight state for diagnostics.
- `lb_app.api.RunService` installs a double Ctrl+C handler:
  - 1st Ctrl+C: logs a warning (\"Press Ctrl+C again to stop the execution\"), no stop is issued.
  - 2nd Ctrl+C: arms a stop via the controller's `StopToken`/state machine; the UI stays alive.
  - Further Ctrl+C while stopping are ignored; termination remains controller-driven.

## Controller State Machine (Phase-Aware)

- States: `INIT -> RUNNING_GLOBAL_SETUP -> RUNNING_WORKLOADS -> RUNNING_GLOBAL_TEARDOWN -> FINISHED`
- Stop path: `... -> STOP_ARMED -> STOPPING_INTERRUPT_SETUP | STOPPING_WAIT_RUNNERS -> STOPPING_TEARDOWN | STOPPING_INTERRUPT_TEARDOWN -> ABORTED`
- Failure path: any state can go to `FAILED` (unexpected error) or `STOP_FAILED` (stop protocol timed out).
- Terminal states: `FINISHED`, `ABORTED`, `STOP_FAILED`, `FAILED`.
- Cleanup gating: only `FINISHED` or `ABORTED` set `cleanup_allowed=True`; `STOP_FAILED`/`FAILED` keep provisioned nodes for inspection.

## Phase-Aware Stop Semantics

- **Global Setup**: stop -> `STOPPING_INTERRUPT_SETUP`; interrupt current playbook; proceed to teardown; finish as `ABORTED`.
- **Workloads**: stop -> `STOPPING_WAIT_RUNNERS`; send stop file; wait for runner confirmations by `run_id`; on success -> `STOPPING_TEARDOWN`, else `STOP_FAILED`.
- **Global Teardown**: stop -> `STOPPING_INTERRUPT_TEARDOWN`; interrupt playbook; outcome `ABORTED` or `STOP_FAILED`.

## Provisioning Cleanup Control

- `RunExecutionSummary.cleanup_allowed` reflects state-machine authorization.
- `lb_ui` destroys provisioned nodes only when `cleanup_allowed=True`; otherwise it preserves them and warns the user.

## Thread Model

- **Controller worker thread** runs orchestration via `ControllerRunner`, sharing the `ControllerStateMachine`.
- **UI/main thread** handles input and logging; SIGINT is converted into queued stop requests, never killing the controller thread.
- **Ansible subprocesses** are session-isolated; interrupted only via controller-driven `interrupt()`.

## Verification Checklist

- `uv run lb run --multipass` (or `--docker`):
  - 1st Ctrl+C during setup: dashboard stays open, warning appears, setup continues.
  - 2nd Ctrl+C during setup: setup playbook interrupted, teardown runs, provisioning cleanup only if `cleanup_allowed=True`.
  - During workloads: stop waits for runner confirmations before teardown.
  - During teardown: stop interrupts teardown and ends in `ABORTED` or `STOP_FAILED`, nodes preserved if not authorized for cleanup.
