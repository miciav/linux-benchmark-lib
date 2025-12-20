# Interrupt Handling Design

This document describes the double-Ctrl+C interruption handling for remote benchmarks.

## Goals

- Prevent accidental stops of long-running benchmarks.
- Ensure graceful teardown of remote workloads when a stop is confirmed.
- Provide clear UI feedback.

## Architecture

The interrupt handling logic is separated into three layers:

1. **State Machine (`DoubleCtrlCStateMachine`)**
   - Pure logic component in `lb_controller/interrupts.py`.
   - Tracks states: `RUNNING` -> `STOP_ARMED` -> `STOPPING` -> `FINISHED`.
   - Decides action: `WARN_ARM`, `REQUEST_STOP`, or `DELEGATE` (allow default/force kill).

2. **Handler (`SigintDoublePressHandler`)**
   - Context manager that installs/restores `signal.signal(SIGINT, ...)`.
   - Routes signals to the state machine.
   - Executes callbacks based on decision (`on_first_sigint`, `on_confirmed_sigint`).

3. **Orchestration (`RunService`, `BenchmarkController`)**
   - `lb_app.services.run_service.RunService` installs the handler and provides UI callbacks.
   - `StopToken` in `lb_runner.stop_token` signals intent to stop across threads/processes.
   - `BenchmarkController` and `ControllerRunner` observe the token and coordinate teardown.
   - `AnsibleRunnerExecutor` interrupts active playbooks when a stop is requested.

## Behavior

- **First Ctrl+C**
  - State: `RUNNING` -> `STOP_ARMED`.
  - Action: log "Press Ctrl+C again to stop...". Execution continues.
- **Second Ctrl+C**
  - State: `STOP_ARMED` -> `STOPPING`.
  - Action: trigger `StopToken`.
    - Active Ansible playbook is terminated.
    - Controller loop breaks.
    - Plugin teardown runs (non-cancellable).
    - Global teardown runs (non-cancellable).
- **Third Ctrl+C (Force)**
  - State: `STOPPING`.
  - Action: delegate to Python default handler for a forced exit if teardown hangs.

## Files

- `lb_controller/interrupts.py`: state machine and handler.
- `lb_app/services/run_service.py`: wiring to UI and controller.
- `lb_controller/controller.py`: phase-aware stop logic.
- `lb_controller/ansible_executor.py`: playbook interruption.
