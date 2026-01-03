# DFAAS-QUALITY-1: Improve error handling

## Context
The DFaaS plugin has 15+ instances of broad exception handling (`except Exception`) with `noqa: BLE001` suppression. This masks specific errors and makes debugging difficult.

## Goal
Replace broad exception catching with specific exception types and appropriate handling strategies.

## Scope
- Define custom exception hierarchy
- Replace `except Exception` with specific catches
- Add retry logic for transient failures
- Improve error messages

## Non-scope
- Changing error recovery behavior
- Adding circuit breakers
- Distributed tracing

## Current State
Broad exception patterns in the codebase:

```python
# generator.py - 10+ occurrences
except Exception as exc:  # noqa: BLE001
    logger.error("Failed config %s: %s", cfg_id, exc)

# queries.py
except Exception as exc:  # noqa: BLE001
    raise PrometheusQueryError(...)

# test files
except Exception as exc:  # noqa: BLE001
    _skip_or_fail(...)
```

Problems:
- All exceptions treated equally
- No differentiation between transient and permanent failures
- Difficult to debug specific issues
- `noqa` comments hide linting violations

## Proposed Design

### Exception Hierarchy
```python
# lb_plugins/plugins/dfaas/exceptions.py

class DfaasError(Exception):
    """Base exception for DFaaS plugin."""
    pass

class ConfigurationError(DfaasError):
    """Invalid configuration or missing requirements."""
    pass

class K6ExecutionError(DfaasError):
    """k6 execution failed."""
    def __init__(self, config_id: str, message: str, returncode: int | None = None):
        self.config_id = config_id
        self.returncode = returncode
        super().__init__(f"k6 execution failed for {config_id}: {message}")

class PrometheusError(DfaasError):
    """Prometheus query or connection error."""
    pass

class PrometheusConnectionError(PrometheusError):
    """Cannot connect to Prometheus."""
    pass

class PrometheusQueryError(PrometheusError):
    """Query returned error or invalid data."""
    pass

class CooldownTimeoutError(DfaasError):
    """Cooldown wait exceeded max time."""
    def __init__(self, waited_seconds: int, max_seconds: int):
        self.waited_seconds = waited_seconds
        self.max_seconds = max_seconds
        super().__init__(f"Cooldown timeout after {waited_seconds}s (max: {max_seconds}s)")

class SSHConnectionError(DfaasError):
    """SSH connection to k6 host failed."""
    pass

class OpenFaaSError(DfaasError):
    """OpenFaaS API error."""
    pass
```

### Retry Logic
```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

class MetricsCollector:
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(PrometheusConnectionError),
    )
    def collect_node_metrics(self, ...) -> NodeMetrics:
        try:
            return self._runner.execute(...)
        except urllib.error.URLError as e:
            raise PrometheusConnectionError(f"Cannot connect: {e}") from e
        except json.JSONDecodeError as e:
            raise PrometheusQueryError(f"Invalid response: {e}") from e
```

### Specific Catches
```python
# Before
try:
    summary = self._run_k6(cfg_id, script)
except Exception as exc:  # noqa: BLE001
    logger.error("Failed: %s", exc)
    skipped_rows.append(...)

# After
try:
    summary = self._k6_runner.execute(cfg_id, script, target_name, run_id)
except K6ExecutionError as exc:
    logger.error("k6 failed for config %s: %s", exc.config_id, exc)
    self._record_failed_config(config_pairs, exc)
except SSHConnectionError as exc:
    logger.error("SSH connection failed: %s", exc)
    raise  # Cannot continue without SSH
except PrometheusError as exc:
    logger.warning("Metrics collection failed: %s", exc)
    # Continue with NaN metrics
```

## Partial Objectives + Tests

### Objective 1: Define exception hierarchy
Create `exceptions.py` with all custom exceptions.
**Tests**:
- Unit test: exception inheritance
- Unit test: exception messages include context

### Objective 2: Replace catches in generator.py
Update all `except Exception` blocks.
**Tests**:
- Unit test: specific exceptions raised and caught
- Verify no `noqa: BLE001` remains

### Objective 3: Replace catches in queries.py
Update Prometheus query error handling.
**Tests**:
- Unit test: connection errors vs query errors

### Objective 4: Add retry logic
Implement retry for transient failures.
**Tests**:
- Unit test: retry on connection error
- Unit test: no retry on query error
- Unit test: max retries exceeded

### Objective 5: Update tests
Remove `noqa: BLE001` from test files where possible.
**Tests**:
- All tests pass
- Linting passes without suppressions

## Acceptance Criteria
- [ ] Custom exception hierarchy defined
- [ ] No `noqa: BLE001` in production code
- [ ] Transient failures retried with backoff
- [ ] Error messages include actionable context
- [ ] All tests pass

## Files to Create
- `lb_plugins/plugins/dfaas/exceptions.py`

## Files to Modify
- `lb_plugins/plugins/dfaas/generator.py`
- `lb_plugins/plugins/dfaas/queries.py`
- `lb_plugins/plugins/dfaas/services/k6_runner.py`
- `lb_plugins/plugins/dfaas/services/cooldown.py`
- `lb_plugins/plugins/dfaas/services/metrics_collector.py`

## Dependencies
- 016 (decomposition complete)

## Effort
~3 hours

