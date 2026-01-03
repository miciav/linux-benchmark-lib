# Fix 161 Ruff linting errors

## Problem

The codebase has **161 linting errors** detected by Ruff, including:

- **79 unused imports** (F401) - code bloat, slower imports
- **23 imports not at top of file** (E402) - non-standard layout
- **13 redefined while unused** (F811) - potential bugs
- **12 undefined with import star** (F405) - dangerous imports
- **5 unused variables** (F841) - dead code

## Evidence

**Ruff stats** (`arch_report/ruff_stats.txt`):
```
79  F401  [-] unused-import
23  E402  [ ] module-import-not-at-top-of-file
13  F811  [-] redefined-while-unused
12  F405  [ ] undefined-local-with-import-star-usage
 9  E701  [ ] multiple-statements-on-one-line-colon
 9  F822  [ ] undefined-export
 5  F841  [ ] unused-variable
 3  F541  [*] f-string-missing-placeholders
 2  E731  [ ] lambda-assignment
 2  E741  [ ] ambiguous-variable-name
 2  F821  [ ] undefined-name
 1  F402  [ ] import-shadowed-by-loop-var
 1  F403  [ ] undefined-local-with-import-star
Found 161 errors.
[*] 85 fixable with the `--fix` option
```

## Solution

### Phase 1: Auto-fix 85 errors

Run Ruff with `--fix` to automatically fix safe issues:

```bash
# Preview what will be fixed
uv run ruff check . --fix --diff

# Apply fixes
uv run ruff check . --fix

# Apply unsafe fixes (review carefully)
uv run ruff check . --fix --unsafe-fixes
```

**Auto-fixable categories**:
- `F401` (unused imports) - 79 issues
- `F541` (f-string without placeholders) - 3 issues
- Some `F811` (redefined while unused)

### Phase 2: Manual fixes for remaining 76 errors

#### E402: Imports not at top of file (23 issues)

**Problem**: Imports placed after code execution.

```python
# Before
import sys
sys.path.insert(0, "...")  # Code before import
import my_module

# After
import sys
sys.path.insert(0, "...")
import my_module  # Move all imports to top if possible
```

**Alternative**: If import order matters (path manipulation), add noqa:
```python
sys.path.insert(0, "...")
import my_module  # noqa: E402
```

#### F405: Undefined with import star (12 issues)

**Problem**: Using `from module import *` then referencing undefined names.

```python
# Before
from some_module import *
x = undefined_name  # F405

# After
from some_module import specific_name
x = specific_name
```

**Action**: Replace all `import *` with explicit imports.

#### E701: Multiple statements on one line (9 issues)

**Problem**: `if x: return y` on single line.

```python
# Before
if condition: return value

# After
if condition:
    return value
```

#### F822: Undefined export (9 issues)

**Problem**: `__all__` contains names not defined in module.

```python
# Before
__all__ = ["Foo", "Bar", "Baz"]  # But Baz doesn't exist

# After
__all__ = ["Foo", "Bar"]  # Only defined names
```

#### F841: Unused variable (5 issues)

**Problem**: Variable assigned but never used.

```python
# Before
result = compute_something()  # never used

# After
_ = compute_something()  # Use underscore for intentionally unused
# or simply remove the assignment
compute_something()
```

#### F811: Redefined while unused (13 issues)

**Problem**: Same name defined twice, first never used.

```python
# Before
def foo():
    pass

def foo():  # F811 - redefines foo
    pass

# After - remove first definition or rename
def foo_v1():
    pass

def foo():
    pass
```

## Implementation Steps

### Step 1: Create a branch
```bash
git checkout -b fix/ruff-linting-errors
```

### Step 2: Auto-fix safe issues
```bash
uv run ruff check . --fix
git add -A && git commit -m "fix: auto-fix 85 ruff linting errors"
```

### Step 3: Fix E402 issues manually
```bash
uv run ruff check . --select=E402
# Fix each file
git add -A && git commit -m "fix: move imports to top of file (E402)"
```

### Step 4: Fix F405 issues (remove import *)
```bash
uv run ruff check . --select=F405
# Replace import * with explicit imports
git add -A && git commit -m "fix: replace import * with explicit imports (F405)"
```

### Step 5: Fix remaining issues
```bash
uv run ruff check .
# Fix remaining issues one category at a time
```

### Step 6: Run tests
```bash
uv run pytest tests/ -v
```

### Step 7: Verify clean
```bash
uv run ruff check .
# Should show: All checks passed!
```

## Risk Assessment

| Category | Risk | Notes |
|----------|------|-------|
| F401 (unused imports) | **Low** | Safe to remove |
| E402 (import order) | **Low** | May need noqa for path manipulation |
| F405 (import *) | **Medium** | Need to identify correct imports |
| F811 (redefined) | **Medium** | May indicate design issues |
| F841 (unused var) | **Low** | Check if intentional |

## Acceptance Criteria

- [ ] `ruff check .` shows 0 errors
- [ ] All tests pass
- [ ] No new `# noqa` comments added (except where truly necessary)
- [ ] All `import *` statements removed
- [ ] PR with clean commit history (one commit per category)
