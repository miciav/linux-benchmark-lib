# Issue 005: [Stage 2] Refactor LocalRunner Responsibilities

## Context
`lb_runner.engine.runner.LocalRunner` is a complex class (22 methods) that manages:
- Plugin loading and validation
- The main execution loop
- Metric collection (starting/stopping collectors)
- Signal handling

It is becoming hard to maintain and test.

## Goal
Extract metric collection management into a dedicated collaborator.

## Action Plan

### 1. Extract MetricManager
- [ ] Create `lb_runner.engine.metrics.MetricManager`.
- [ ] Move logic for initializing, starting, and stopping collectors from `LocalRunner` to `MetricManager`.

### 2. Integrate
- [ ] Inject `MetricManager` into `LocalRunner`.
- [ ] Update `LocalRunner` to delegate metric operations to `MetricManager`.

## Acceptance Criteria
- `LocalRunner` no longer directly iterates over collectors.
- Benchmarks still produce metric data in `benchmark_results/`.
