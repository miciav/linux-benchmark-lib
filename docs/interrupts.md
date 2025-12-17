# Interrupt Handling Design

This document describes the double-Ctrl+C interruption handling mechanism for remote benchmarks.

## Goals
*   Prevent accidental stops of long-running benchmarks.
*   Ensure graceful teardown of remote workloads when a stop is confirmed.
*   Provide clear UI feedback.

## Architecture

The interrupt handling logic is separated into three layers:

1.  **State Machine (`DoubleCtrlCStateMachine`)**:
    *   Pure logic component.
    *   Tracks states: `RUNNING` -> `STOP_ARMED` -> `STOPPING` -> `FINISHED`.
    *   Decides action: `WARN_ARM`, `REQUEST_STOP`, or `DELEGATE` (allow default/force kill).

2.  **Handler (`SigintDoublePressHandler`)**:
    *   Context manager that installs/restores `signal.signal(SIGINT, ...)`.
    *   Routes signals to the state machine.
    *   Executes callbacks based on decision (`on_first_sigint`, `on_confirmed_sigint`).

3.  **Orchestration (`RunService`, `BenchmarkController`)**:
    *   `RunService` installs the handler and provides the UI callbacks.
    *   `StopToken` is used to signal the intent to stop across threads/processes.
    *   `BenchmarkController` monitors the `StopToken`.
    *   `AnsibleRunnerExecutor` kills the active playbook process when the token triggers.

## Behavior

*   **First Ctrl+C**:
    *   State: `RUNNING` -> `STOP_ARMED`.
    *   Action: Log "Press Ctrl+C again to stop...". Execution continues.
*   **Second Ctrl+C**:
    *   State: `STOP_ARMED` -> `STOPPING`.
    *   Action: Trigger `StopToken`.
        *   Active Ansible playbook is terminated.
        *   Controller loop breaks.
        *   **Plugin Teardown** runs (non-cancellable).
        *   **Global Teardown** runs (non-cancellable).
*   **Third Ctrl+C (Force)**:
    *   State: `STOPPING`.
    *   Action: Delegate to Python default handler (raises `KeyboardInterrupt` or exits), allowing a forced kill if teardown hangs.

## Files
*   `lb_controller/interrupts.py`: State machine and handler.
*   `lb_controller/services/run_service.py`: Integration with UI and Controller.
*   `lb_controller/controller.py`: Logic to ensure teardown runs on stop.
*   `lb_controller/ansible_executor.py`: Process termination logic.
