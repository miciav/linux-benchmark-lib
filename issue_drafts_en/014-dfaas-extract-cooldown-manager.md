# DFAAS-REFACTOR-2: Extract CooldownManager

## Context
Cooldown logic is embedded in `DfaasGenerator._cooldown()` method, mixing metric querying with threshold evaluation and wait logic.

## Goal
Extract cooldown functionality into a dedicated `CooldownManager` class with clear responsibilities.

## Scope
- Extract cooldown wait logic
- Extract threshold evaluation
- Make cooldown parameters injectable
- Maintain backward compatibility

## Non-scope
- Changing cooldown algorithm
- Adding new cooldown strategies
- Prometheus query changes

## Current State
The `_cooldown()` method (lines 506-532) handles:
- Reading cooldown config (max_wait, sleep_step, threshold)
- Querying node metrics via Prometheus
- Checking replica counts via faas-cli
- Evaluating threshold conditions
- Sleep/retry loop

```python
def _cooldown(
    self,
    runner: PrometheusQueryRunner,
    queries: dict[str, QueryDefinition],
    base_idle: MetricsSnapshot,
    function_names: list[str],
) -> tuple[MetricsSnapshot, int]:
    # 27 lines of mixed concerns
```

## Proposed Design

### CooldownManager Interface
```python
@dataclass
class CooldownResult:
    snapshot: MetricsSnapshot
    waited_seconds: int
    iterations: int

class CooldownManager:
    def __init__(
        self,
        max_wait_seconds: int,
        sleep_step_seconds: int,
        idle_threshold_pct: float,
        metrics_provider: Callable[[], MetricsSnapshot],
        replicas_provider: Callable[[list[str]], dict[str, int]],
    ) -> None: ...

    def wait_for_idle(
        self,
        baseline: MetricsSnapshot,
        function_names: list[str],
    ) -> CooldownResult: ...

    def is_within_threshold(
        self,
        current: MetricsSnapshot,
        baseline: MetricsSnapshot,
    ) -> bool: ...
```

### Usage in Generator
```python
def _run_command(self) -> None:
    # Setup
    cooldown_mgr = CooldownManager(
        max_wait_seconds=self.config.cooldown.max_wait_seconds,
        sleep_step_seconds=self.config.cooldown.sleep_step_seconds,
        idle_threshold_pct=self.config.cooldown.idle_threshold_pct,
        metrics_provider=lambda: self._query_node_metrics(runner, queries, None, None),
        replicas_provider=self._get_function_replicas,
    )

    # In loop
    result = cooldown_mgr.wait_for_idle(base_idle, function_names)
```

## Partial Objectives + Tests

### Objective 1: Create CooldownManager class
Define interface and basic structure.
**Tests**:
- Unit test: `test_cooldown_manager_init`

### Objective 2: Implement threshold evaluation
Extract `_within_threshold` logic.
**Tests**:
- Unit test: `test_cooldown_within_threshold_cpu`
- Unit test: `test_cooldown_within_threshold_ram`
- Unit test: `test_cooldown_within_threshold_nan_values`

### Objective 3: Implement wait loop
Extract wait/retry logic with timeout.
**Tests**:
- Unit test: `test_cooldown_wait_succeeds_immediately`
- Unit test: `test_cooldown_wait_retries_until_idle`
- Unit test: `test_cooldown_wait_timeout_raises`

### Objective 4: Update generator
Replace `_cooldown` with CooldownManager.
**Tests**:
- Existing tests pass
- Integration test with mocked providers

## Acceptance Criteria
- [ ] CooldownManager handles all cooldown concerns
- [ ] Generator uses CooldownManager via dependency injection
- [ ] All existing tests pass
- [ ] New unit tests for CooldownManager
- [ ] Cooldown logic testable in isolation

## Files to Create
- `lb_plugins/plugins/dfaas/services/cooldown.py`
- `tests/unit/lb_plugins/test_dfaas_cooldown.py`

## Files to Modify
- `lb_plugins/plugins/dfaas/generator.py`
- `lb_plugins/plugins/dfaas/services/__init__.py`

## Dependencies
- 013 (K6Runner extraction)

## Effort
~3 hours

