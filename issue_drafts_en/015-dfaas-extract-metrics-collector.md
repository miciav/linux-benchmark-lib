# DFAAS-REFACTOR-3: Extract MetricsCollector

## Context
Prometheus query logic is scattered across multiple methods in `DfaasGenerator`, with direct `PrometheusQueryRunner` usage mixed with business logic.

## Goal
Extract metrics collection into a dedicated `MetricsCollector` class that wraps Prometheus queries with caching and retry logic.

## Scope
- Extract node metrics querying
- Extract function metrics querying
- Add optional caching layer
- Maintain backward compatibility

## Non-scope
- Changing Prometheus queries
- Adding new metrics
- Query optimization

## Current State
Metrics-related methods in `generator.py`:
- `_query_node_metrics()` (lines 534-568) - Node CPU/RAM/power
- `_query_metrics()` (lines 570-629) - Full metrics including per-function
- `MetricsSnapshot` dataclass (lines 40-44)

These methods:
- Create `PrometheusQueryRunner` inline
- Handle query errors with broad exception catching
- Mix metric collection with data transformation

## Proposed Design

### MetricsCollector Interface
```python
@dataclass
class NodeMetrics:
    cpu: float
    ram: float
    ram_pct: float
    power: float
    timestamp: float

@dataclass
class FunctionMetrics:
    cpu: float
    ram: float
    power: float

@dataclass
class CollectedMetrics:
    node: NodeMetrics
    functions: dict[str, FunctionMetrics]
    duration_seconds: float

class MetricsCollector:
    def __init__(
        self,
        prometheus_url: str,
        queries: dict[str, QueryDefinition],
        duration: str,
        scaphandre_enabled: bool = False,
        function_pid_regexes: dict[str, str] | None = None,
        cache_ttl_seconds: float = 0,
    ) -> None: ...

    def collect_node_metrics(
        self,
        start_time: float | None = None,
        end_time: float | None = None,
    ) -> NodeMetrics: ...

    def collect_function_metrics(
        self,
        function_names: list[str],
        start_time: float | None = None,
        end_time: float | None = None,
    ) -> dict[str, FunctionMetrics]: ...

    def collect_all(
        self,
        function_names: list[str],
        start_time: float,
        end_time: float,
    ) -> CollectedMetrics: ...
```

### Caching Strategy
Optional time-based cache for repeated queries:
```python
class MetricsCollector:
    def __init__(self, ..., cache_ttl_seconds: float = 0):
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cache_ttl = cache_ttl_seconds

    def _cached_query(self, key: str, query_fn: Callable) -> Any:
        if self._cache_ttl <= 0:
            return query_fn()
        now = time.time()
        if key in self._cache:
            ts, value = self._cache[key]
            if now - ts < self._cache_ttl:
                return value
        value = query_fn()
        self._cache[key] = (now, value)
        return value
```

## Partial Objectives + Tests

### Objective 1: Create MetricsCollector class
Define interface and dataclasses.
**Tests**:
- Unit test: `test_metrics_collector_init`

### Objective 2: Implement node metrics collection
Move `_query_node_metrics` logic.
**Tests**:
- Unit test: `test_collect_node_metrics` (mocked Prometheus)
- Unit test: `test_collect_node_metrics_with_scaphandre`

### Objective 3: Implement function metrics collection
Move per-function query logic.
**Tests**:
- Unit test: `test_collect_function_metrics` (mocked)
- Unit test: `test_collect_function_metrics_handles_errors`

### Objective 4: Add caching layer
Implement optional TTL-based caching.
**Tests**:
- Unit test: `test_metrics_collector_caches_results`
- Unit test: `test_metrics_collector_cache_expires`

### Objective 5: Update generator
Replace direct queries with MetricsCollector.
**Tests**:
- Existing tests pass
- Integration test with mocked collector

## Acceptance Criteria
- [ ] MetricsCollector encapsulates all Prometheus queries
- [ ] Generator uses MetricsCollector
- [ ] All existing tests pass
- [ ] New unit tests for MetricsCollector
- [ ] Optional caching reduces query overhead

## Files to Create
- `lb_plugins/plugins/dfaas/services/metrics_collector.py`
- `tests/unit/lb_plugins/test_dfaas_metrics_collector.py`

## Files to Modify
- `lb_plugins/plugins/dfaas/generator.py`
- `lb_plugins/plugins/dfaas/services/__init__.py`

## Dependencies
- 014 (CooldownManager extraction)

## Effort
~3 hours

