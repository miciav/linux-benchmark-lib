# Issue 004: [Stage 2] Decompose RunService God Object

## Context
`lb_app.services.RunService` is a monolithic class with 36 methods. It handles:
- Config loading
- Local benchmark execution
- Remote benchmark orchestration
- Output formatting
- Error handling

This violates the Single Responsibility Principle (SRP).

## Goal
Split `RunService` into smaller, focused collaborators. `RunService` should remain as a thin facade/coordinator.

## Action Plan

### 1. Create Executors
- [ ] Create `lb_app.execution.local.LocalExecutor` to handle local run logic.
- [ ] Create `lb_app.execution.remote.RemoteExecutor` to handle remote run logic.

### 2. Move Logic
- [ ] Move local run methods from `RunService` to `LocalExecutor`.
- [ ] Move remote run methods from `RunService` to `RemoteExecutor`.

### 3. Refactor RunService
- [ ] Inject `LocalExecutor` and `RemoteExecutor` into `RunService`.
- [ ] Update `RunService.run_benchmark` to delegate to the appropriate executor based on the config.

## Acceptance Criteria
- `RunService` has < 15 methods.
- Local and Remote runs still work (verified by manual run or e2e tests).
