# Distributed Stop & Multipass Lifecycle Design

## Overview
This document describes the robust double-Ctrl+C handling and distributed shutdown protocol for the Linux Benchmark Library.

## Ownership
*   **Ctrl+C Handling**: `lb_controller.interrupts.SigintDoublePressHandler` (UI Layer/Service).
*   **Stop Coordination**: `lb_controller.stop_coordinator.StopCoordinator` (Controller Layer).
*   **Teardown Execution**: `BenchmarkController` (Controller Layer).
*   **Multipass Lifecycle**: handled via `lb_provisioner` (Multipass backend), managed by `RunService`.

## State Machine (Stop Coordinator)
*   `IDLE`: Normal execution.
*   `STOPPING_WORKLOADS`: Stop requested, waiting for runner confirmations.
*   `TEARDOWN_READY`: All runners confirmed stop. Safe to teardown.
*   `STOP_FAILED`: Timeout or failure. Unsafe to teardown.

## Stop Protocol
1.  **Request**: Controller runs an Ansible task to create `STOP` file on all remote hosts.
2.  **Reaction**: `lb_runner` (on remote) detects `STOP` file via `StopToken`, stops workload, and emits `status="stopped"`.
3.  **Confirmation**: Controller receives event, updates Coordinator.
4.  **Decision**:
    *   If all confirmed -> Run Teardown.
    *   If timeout/fail -> Skip Teardown, Flag run as failed.

## Multipass Invariants
*   **Preservation**: VM is preserved if the stop protocol fails or times out (debugging mode).
*   **Destruction**: VM is destroyed only if the run completes normally OR the stop protocol succeeds (graceful teardown).
*   **Implementation**: Provisioning backends yield `RemoteHostConfig` objects with destroy hooks; `RunService` tears them down unless the run fails stop protocol.

## Key Files
*   `lb_controller/stop_coordinator.py`: New coordinator logic.
*   `lb_controller/controller.py`: Integrated protocol into main loop.
*   `lb_controller/services/multipass_service.py`: Lifecycle control.
*   `lb_runner/local_runner.py`: Explicit stop status emission.
