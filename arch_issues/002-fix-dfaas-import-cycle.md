# Fix import cycle in dfaas plugin

## Problem

There is a circular import dependency in the dfaas plugin:

```
lb_plugins.plugins.dfaas.generator
    → lb_plugins.plugins.dfaas.plugin
    → lb_plugins.plugins.dfaas.generator
```

This cycle:
1. **Breaks modularity** - generator and plugin are tightly coupled
2. **Causes import errors** - can fail at runtime depending on import order
3. **Prevents testing in isolation** - can't test generator without plugin

## Evidence

**Grimp cycles report** (`arch_report/grimp_cycles.txt`):
```
Import cycles in lb_plugins: 1
  - lb_plugins.plugins.dfaas.generator -> lb_plugins.plugins.dfaas.plugin -> lb_plugins.plugins.dfaas.generator
```

## Root Cause Analysis

Looking at the imports:

**generator.py** imports from plugin.py:
- Likely imports `DfaasPlugin` or plugin-level constants

**plugin.py** imports from generator.py:
- Imports `DfaasGenerator` to instantiate in `create_generator()`

## Solution

### Option A: Extract shared types to a new module (Recommended)

Create `lb_plugins/plugins/dfaas/types.py` for shared types:

```python
# lb_plugins/plugins/dfaas/types.py
"""Shared types and constants for dfaas plugin."""

from dataclasses import dataclass
from typing import List, Dict, Any

@dataclass
class DfaasResult:
    """Result from a dfaas benchmark run."""
    success: bool
    metrics: Dict[str, Any]
    k6_output: str
    # ... other shared types
```

Then update imports:
- `generator.py`: imports from `types.py` instead of `plugin.py`
- `plugin.py`: imports from `types.py` and `generator.py`

### Option B: Use TYPE_CHECKING guard

```python
# generator.py
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .plugin import DfaasPlugin  # Only for type hints
```

### Option C: Lazy import in generator

```python
# generator.py
def some_method(self):
    from .plugin import something  # Import inside method
```

## Implementation Steps

### Step 1: Identify what generator imports from plugin
```bash
grep -n "from.*plugin import\|import.*plugin" lb_plugins/plugins/dfaas/generator.py
```

### Step 2: Create types.py with shared types
```python
# lb_plugins/plugins/dfaas/types.py
# Move shared types here
```

### Step 3: Update generator.py imports
```python
# Before
from .plugin import SomeType

# After
from .types import SomeType
```

### Step 4: Verify cycle is broken
```bash
uv run grimp lb_plugins --show-cycles
```

### Step 5: Run tests
```bash
uv run pytest tests/unit/lb_plugins/test_dfaas*.py -v
```

## Risk Assessment

| Aspect | Level | Notes |
|--------|-------|-------|
| Risk | **Medium** | Changing import structure |
| Effort | **Low** | ~1 hour |
| Validation | Grimp check + unit tests |

## Acceptance Criteria

- [ ] `grimp` reports 0 cycles in lb_plugins
- [ ] `lb_plugins/plugins/dfaas/types.py` created (if using Option A)
- [ ] All dfaas tests pass
- [ ] No runtime import errors
