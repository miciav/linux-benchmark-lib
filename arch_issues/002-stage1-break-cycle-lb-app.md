# Issue 002: [Stage 1] Break Import Cycle in lb_app

## Context
A circular dependency exists in `lb_app`:
`lb_app.services.remote_run_coordinator` -> `lb_app.services.run_service` -> `lb_app.services.remote_run_coordinator`.

This makes it impossible to import `RunService` in isolation and indicates a design flaw where the "Coordinator" (which should be lower level or parallel) depends on the main "Service" (which depends on the Coordinator).

## Goal
Remove the import cycle to improve modularity and testability.

## Action Plan

### 1. Analyze the dependency
- Check why `remote_run_coordinator` needs `run_service`. It likely needs shared type definitions or a callback interface.

### 2. Extract Shared Types or Interface
- [ ] Create `lb_app.execution.interfaces.py` (or similar).
- [ ] Define an interface `IRunCoordinator` if `RunService` just needs to call it.
- [ ] Move shared data structures (like `RunContext` or `RunStatus`) to `lb_app.services.types` or `lb_app.common`.

### 3. Update Imports
- [ ] Update `run_service.py` to depend on the new interface/types.
- [ ] Update `remote_run_coordinator.py` to implement the interface or use the common types.
- [ ] Verify the cycle is gone using `grimp` or the `arch_audit.sh` script.

## Acceptance Criteria
- `arch_report/grimp_cycles.txt` shows 0 cycles for `lb_app`.
- All tests pass.
