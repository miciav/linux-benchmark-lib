# ISSUE-006: Test Markers Standardization

## Summary

Test markers are inconsistently applied across the test suite, making it difficult to run specific subsets of tests. A standardized marker hierarchy is needed to enable precise test selection.

## Current State

### Existing Markers (from `pyproject.toml`)

```toml
markers = [
    "unit",
    "integration",
    "e2e",
    "docker",
    "multipass",
    "slow",
    "slowest",
]
```

### Actual Usage in Test Files

```python
# Some files use module-specific markers
pytestmark = pytest.mark.unit_runner

# Some use generic markers
@pytest.mark.unit
def test_something(): ...

# Some have no markers at all
def test_something_else(): ...
```

### Inconsistencies Found

| File | Marker Used | Expected |
|------|-------------|----------|
| `test_local_runner_unit.py` | `unit_runner` | ✅ Good |
| `test_executor.py` | None | ❌ Missing |
| `test_benchmark_config.py` | None | ❌ Missing |
| `test_controller.py` | None | ❌ Missing |

## Problem Analysis

1. **Cannot run module-specific tests**: `pytest -m unit_controller` fails to find tests missing the marker.

2. **Marker naming inconsistency**: Mix of `unit_runner`, `unit`, and no markers.

3. **Missing granularity**: No way to run "all executor tests" or "all config tests".

4. **Documentation gap**: Available markers aren't documented in CLAUDE.md.

## Proposed Resolution

### Hierarchical Marker System

```
unit
├── unit_runner
│   ├── unit_runner_engine
│   │   ├── unit_runner_executor
│   │   ├── unit_runner_context
│   │   ├── unit_runner_planning
│   │   └── unit_runner_metrics
│   ├── unit_runner_services
│   └── unit_runner_models
├── unit_controller
│   ├── unit_controller_ansible
│   ├── unit_controller_services
│   └── unit_controller_state
├── unit_plugins
│   ├── unit_plugins_dfaas
│   ├── unit_plugins_stress
│   └── unit_plugins_io
├── unit_ui
├── unit_analytics
├── unit_provisioner
└── unit_common
```

### Usage Examples

```bash
# All unit tests
pytest -m unit

# All runner tests
pytest -m unit_runner

# Just executor tests
pytest -m unit_runner_executor

# All controller ansible tests
pytest -m unit_controller_ansible

# Multiple specific areas
pytest -m "unit_runner_engine or unit_controller_state"
```

## Action Plan

### Step 1: Update `pyproject.toml` Markers

```toml
[tool.pytest.ini_options]
markers = [
    # Test levels
    "unit: Unit tests (fast, isolated)",
    "integration: Integration tests (service-level)",
    "e2e: End-to-end tests (full stack)",

    # Infrastructure markers
    "docker: Requires Docker",
    "multipass: Requires Multipass VMs",
    "slow: Slow tests (> 10s)",
    "slowest: Very slow tests (> 60s)",

    # Module markers - Runner
    "unit_runner: lb_runner unit tests",
    "unit_runner_engine: Runner engine components",
    "unit_runner_executor: RepetitionExecutor tests",
    "unit_runner_context: RunnerContext tests",
    "unit_runner_planning: RunPlanner tests",
    "unit_runner_metrics: MetricManager tests",
    "unit_runner_services: Runner service layer",
    "unit_runner_models: Runner model tests",

    # Module markers - Controller
    "unit_controller: lb_controller unit tests",
    "unit_controller_ansible: Ansible integration tests",
    "unit_controller_services: Controller service layer",
    "unit_controller_state: State machine tests",

    # Module markers - Other
    "unit_plugins: lb_plugins unit tests",
    "unit_plugins_dfaas: DFaaS plugin tests",
    "unit_ui: lb_ui unit tests",
    "unit_analytics: lb_analytics unit tests",
    "unit_provisioner: lb_provisioner unit tests",
    "unit_common: lb_common unit tests",
]
```

**Estimated effort:** 15 minutes

### Step 2: Create conftest.py Auto-Markers

Add automatic marker inheritance based on file location:

```python
# tests/conftest.py
import pytest
from pathlib import Path

def pytest_collection_modifyitems(session, config, items):
    """Auto-add markers based on test file location."""
    for item in items:
        # Get relative path from tests/
        test_path = Path(item.fspath).relative_to(Path(__file__).parent)
        parts = test_path.parts

        # Add level marker
        if "unit" in parts:
            item.add_marker(pytest.mark.unit)
        elif "integration" in parts:
            item.add_marker(pytest.mark.integration)
        elif "e2e" in parts:
            item.add_marker(pytest.mark.e2e)

        # Add module marker for unit tests
        if len(parts) >= 2 and parts[0] == "unit":
            module = parts[1]  # e.g., "lb_runner", "lb_controller"
            marker_name = f"unit_{module.replace('lb_', '')}"
            item.add_marker(getattr(pytest.mark, marker_name))
```

**Estimated effort:** 30 minutes

### Step 3: Add Explicit Markers to Test Files

For files that need specific sub-markers:

```python
# tests/unit/lb_runner/engine/test_executor.py
import pytest

pytestmark = [
    pytest.mark.unit_runner,
    pytest.mark.unit_runner_engine,
    pytest.mark.unit_runner_executor,
]
```

**Estimated effort:** 2 hours (across all files)

### Step 4: Validate Marker Coverage

Create a validation script:

```python
# scripts/validate_markers.py
"""Ensure all test files have appropriate markers."""

import ast
import sys
from pathlib import Path

def check_file(path: Path) -> list[str]:
    issues = []
    content = path.read_text()
    tree = ast.parse(content)

    has_pytestmark = any(
        isinstance(node, ast.Assign) and
        any(t.id == "pytestmark" for t in node.targets if isinstance(t, ast.Name))
        for node in ast.walk(tree)
    )

    if not has_pytestmark:
        issues.append(f"{path}: Missing pytestmark")

    return issues

if __name__ == "__main__":
    test_dir = Path("tests/unit")
    issues = []
    for py_file in test_dir.rglob("test_*.py"):
        issues.extend(check_file(py_file))

    for issue in issues:
        print(issue)

    sys.exit(1 if issues else 0)
```

**Estimated effort:** 30 minutes

### Step 5: Update CI to Use Markers

```yaml
# .github/workflows/test.yml
jobs:
  unit-tests:
    steps:
      - name: Run unit tests
        run: pytest -m unit --ignore=tests/e2e --ignore=tests/integration

  runner-tests:
    steps:
      - name: Run runner unit tests
        run: pytest -m unit_runner

  controller-tests:
    steps:
      - name: Run controller unit tests
        run: pytest -m unit_controller
```

**Estimated effort:** 20 minutes

### Step 6: Document in CLAUDE.md

Add to CLAUDE.md:

```markdown
## Test Markers

Run specific test subsets using pytest markers:

```bash
pytest -m unit                     # All unit tests
pytest -m unit_runner              # Runner module tests
pytest -m unit_controller          # Controller module tests
pytest -m unit_runner_executor     # Specific component tests
pytest -m "slow and unit_runner"   # Slow runner tests only
```

Available markers are defined in `pyproject.toml`.
```

**Estimated effort:** 10 minutes

## Success Criteria

1. `pytest -m unit_runner` discovers all runner unit tests
2. `pytest -m unit_controller` discovers all controller unit tests
3. Every test file has at least one module marker
4. CI uses markers for test selection
5. CLAUDE.md documents available markers

## Verification Commands

```bash
# Check marker registration
pytest --markers | grep unit_

# Verify discovery
pytest -m unit_runner --collect-only | wc -l
pytest -m unit_controller --collect-only | wc -l

# Find unmarked tests (should be 0)
python scripts/validate_markers.py
```

## Dependencies

- Execute after ISSUE-001 through ISSUE-005 (file relocations)
- Can start Step 1-2 immediately

## References

- CLAUDE.md: Test Organization section
- ANALYSIS.md Section 5: Test Suite Fragmentation
- pytest documentation on markers
