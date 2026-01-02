# DFAAS-QUALITY-5: Improve E2E test resilience

## Context
The DFaaS E2E tests use a `_skip_or_fail` pattern that can silently skip tests in CI, potentially masking real regressions.

## Goal
Improve E2E test resilience with explicit retry logic, better diagnostics, and clear distinction between expected skips and failures.

## Scope
- Add retry logic for transient failures
- Improve diagnostic logging before skip
- Add CI markers for skip tracking
- Maintain test coverage

## Non-scope
- Fundamental test architecture changes
- Removing skip capability entirely
- Adding new E2E tests

## Current State

### _skip_or_fail Pattern
```python
STRICT_MULTIPASS_SETUP = os.environ.get("LB_STRICT_MULTIPASS_SETUP", "").lower() in {
    "1", "true", "yes",
}

def _skip_or_fail(message: str) -> None:
    if STRICT_MULTIPASS_SETUP:
        pytest.fail(message)
    pytest.skip(message)  # Silent skip in non-strict mode
```

### Usage (15+ occurrences)
```python
try:
    _run_playbook(setup_target, ...)
except Exception as exc:  # noqa: BLE001
    _skip_or_fail(f"setup_target failed: {exc}")  # No retry, minimal context
```

Problems:
1. Transient failures cause immediate skip
2. No retry for recoverable errors
3. Minimal diagnostic information logged
4. CI cannot distinguish expected skips from failures

## Proposed Design

### Retry Decorator
```python
from functools import wraps
from typing import TypeVar, Callable
import time

T = TypeVar('T')

def with_retry(
    max_attempts: int = 3,
    delay_seconds: float = 5.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Retry decorator for transient failures."""
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exc: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt < max_attempts:
                        logger.warning(
                            "Attempt %d/%d failed: %s. Retrying in %.1fs...",
                            attempt, max_attempts, exc, delay_seconds
                        )
                        time.sleep(delay_seconds)
            raise last_exc  # type: ignore
        return wrapper
    return decorator
```

### Enhanced Skip Helper
```python
@dataclass
class SkipContext:
    reason: str
    category: str  # "infrastructure", "prerequisite", "timeout", "unknown"
    diagnostics: dict[str, Any]
    retried: bool = False
    attempts: int = 1

def skip_with_context(context: SkipContext) -> None:
    """Skip test with detailed context for CI tracking."""
    # Log full diagnostics
    logger.warning(
        "Skipping test: %s (category=%s, retried=%s, attempts=%d)",
        context.reason,
        context.category,
        context.retried,
        context.attempts,
    )
    for key, value in context.diagnostics.items():
        logger.info("  %s: %s", key, value)

    # Add pytest marker for CI
    pytest.skip(
        f"[{context.category}] {context.reason} "
        f"(attempts={context.attempts}, retried={context.retried})"
    )
```

### Improved Test Pattern
```python
# Before
try:
    _run_playbook(setup_target, ...)
except Exception as exc:  # noqa: BLE001
    _skip_or_fail(f"setup_target failed: {exc}")

# After
@with_retry(max_attempts=2, delay_seconds=10)
def _setup_target_with_retry(playbook, inventory, extravars, env):
    return _run_playbook(playbook, inventory, extravars, env)

try:
    _setup_target_with_retry(setup_target, target_inventory, setup_extravars, ansible_env)
except RuntimeError as exc:
    skip_with_context(SkipContext(
        reason=f"setup_target failed: {exc}",
        category="infrastructure",
        diagnostics={
            "playbook": str(setup_target),
            "inventory": str(target_inventory),
            "target_vm": target_vm["name"],
        },
        retried=True,
        attempts=2,
    ))
```

### CI Markers
```python
# conftest.py
def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "infrastructure_skip: Test skipped due to infrastructure issues"
    )
    config.addinivalue_line(
        "markers",
        "prerequisite_skip: Test skipped due to missing prerequisites"
    )
```

## Partial Objectives + Tests

### Objective 1: Create retry decorator
Implement configurable retry logic.
**Tests**:
- Unit test: retry on transient failure
- Unit test: no retry on success
- Unit test: max attempts respected

### Objective 2: Create skip context helper
Implement enhanced skip logging.
**Tests**:
- Unit test: diagnostics logged
- Unit test: category included in skip message

### Objective 3: Update test patterns
Replace `_skip_or_fail` usage.
**Tests**:
- All E2E tests still work
- Transient failures retried

### Objective 4: Add CI markers
Configure pytest markers for tracking.
**Tests**:
- Markers visible in pytest output
- CI can filter by category

## Acceptance Criteria
- [ ] Transient failures retried before skip
- [ ] Skip reasons include category and diagnostics
- [ ] CI can distinguish skip types
- [ ] All E2E tests pass (or skip with context)
- [ ] Reduced false-positive skips

## Files to Modify
- `tests/e2e/test_dfaas_multipass_e2e.py`
- `tests/conftest.py`

## Files to Create
- `tests/helpers/resilience.py` (retry decorator, skip helper)

## Dependencies
- None (independent)

## Effort
~2 hours

