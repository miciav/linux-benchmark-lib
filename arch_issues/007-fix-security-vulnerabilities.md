# Fix security vulnerabilities

## Problem

Bandit security scan found several vulnerabilities, including one **High severity** issue.

## Evidence

**Bandit report** (`arch_report/bandit.txt`):

### High Severity

| Issue | Location | CWE |
|-------|----------|-----|
| `tarfile.extractall` without validation | `installer.py:120` | CWE-22 (Path Traversal) |

### Medium Severity

| Issue | Location | CWE |
|-------|----------|-----|
| Hardcoded `/tmp` directory | `dd/plugin.py:25` | CWE-377 |
| Hardcoded `/tmp` directory | Multiple locations | CWE-377 |

### Low Severity (Informational)

| Issue | Location | Notes |
|-------|----------|-------|
| `subprocess` module import | Multiple | Expected for CLI tools |
| `subprocess.Popen` without shell | Multiple | Actually safer than shell=True |
| `try: except: pass` | `discovery.py` | Acceptable in some cases |

## Solution

### 1. Fix tarfile.extractall vulnerability (High)

**Current code** (`lb_plugins/installer.py:120`):
```python
with zipfile.ZipFile(archive_path, "r") as zip_ref:
    zip_ref.extractall(tmp_path)  # UNSAFE - no validation
```

**Problem**: Malicious archives can contain files with paths like `../../etc/passwd` (path traversal attack).

**Solution**: Validate members before extraction.

```python
import os
from pathlib import Path

def _safe_extract(archive_path: Path, dest: Path) -> None:
    """Safely extract archive with path traversal protection."""
    if str(archive_path).endswith(".zip"):
        with zipfile.ZipFile(archive_path, "r") as zf:
            for member in zf.namelist():
                # Check for path traversal
                member_path = dest / member
                if not _is_safe_path(dest, member_path):
                    raise ValueError(f"Unsafe path in archive: {member}")
            zf.extractall(dest)
    else:
        with tarfile.open(archive_path) as tf:
            for member in tf.getmembers():
                member_path = dest / member.name
                if not _is_safe_path(dest, member_path):
                    raise ValueError(f"Unsafe path in archive: {member.name}")
            tf.extractall(dest, filter='data')  # Python 3.12+ safe filter


def _is_safe_path(base: Path, path: Path) -> bool:
    """Check if path is safely within base directory."""
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False
```

**Alternative for Python 3.12+**: Use `filter` parameter:
```python
# Python 3.12+ has built-in protection
tf.extractall(dest, filter='data')  # Filters dangerous members
```

### 2. Fix hardcoded /tmp usage (Medium)

**Current code** (`lb_plugins/plugins/dd/plugin.py:25`):
```python
of_path: str = Field(default="/tmp/lb_dd_test", description="Output file path")
```

**Problem**:
- Hardcoded paths are inflexible
- `/tmp` may have restricted permissions
- Potential race conditions with predictable names

**Solution**: Use `tempfile` module:

```python
import tempfile
from pathlib import Path

class DDConfig(BasePluginConfig):
    if_path: str = Field(default="/dev/zero", description="Input file path")
    of_path: str = Field(
        default_factory=lambda: str(Path(tempfile.gettempdir()) / f"lb_dd_test_{os.getpid()}"),
        description="Output file path"
    )
```

Or use a config directory:
```python
of_path: str = Field(
    default="",  # Empty means auto-generate
    description="Output file path (auto-generated if empty)"
)

def _get_output_path(self) -> Path:
    if self.config.of_path:
        return Path(self.config.of_path)
    return Path(tempfile.mkdtemp(prefix="lb_dd_")) / "test_file"
```

### 3. Review subprocess usage (Low - Informational)

Current code uses `subprocess.Popen` without `shell=True`, which is actually **correct and secure**.

```python
# GOOD - shell=False (default)
subprocess.Popen(cmd, ...)

# BAD - shell=True (vulnerable to injection)
subprocess.Popen(cmd, shell=True, ...)
```

**Action**: No changes needed, but add comment for clarity:

```python
# Security: Using shell=False to prevent command injection
self._process = subprocess.Popen(cmd, **spec.popen_kwargs)
```

### 4. Review try/except/pass patterns (Low)

**Current code** (`lb_plugins/discovery.py`):
```python
try:
    path.mkdir(parents=True, exist_ok=True)
except Exception:
    pass
```

**This is acceptable** because:
1. Directory creation failure is non-fatal
2. Caller handles missing directory case
3. Comment explains why

**Action**: Ensure all `except: pass` have explanatory comments:

```python
try:
    path.mkdir(parents=True, exist_ok=True)
except Exception:
    # Directory creation may fail for read-only locations; caller handles.
    pass
```

## Implementation Steps

### Step 1: Fix tarfile vulnerability (High priority)
```bash
# Edit lb_plugins/installer.py
# Add _safe_extract and _is_safe_path functions
# Replace extractall calls
```

### Step 2: Run security scan
```bash
uv run bandit -r lb_plugins -ll  # Only medium+ severity
```

### Step 3: Fix hardcoded /tmp
```bash
# Edit lb_plugins/plugins/dd/plugin.py
# Use tempfile module
```

### Step 4: Run tests
```bash
uv run pytest tests/unit/lb_plugins/ -v
```

### Step 5: Final security scan
```bash
uv run bandit -r . -ll
# Should show no High/Medium issues in main code
```

## Risk Assessment

| Fix | Risk | Notes |
|-----|------|-------|
| tarfile.extractall | **Low** | Adding validation, not changing behavior |
| /tmp hardcoding | **Low** | Default change, backward compatible |
| subprocess comments | **None** | Documentation only |

## Acceptance Criteria

- [ ] No High severity bandit issues
- [ ] No Medium severity bandit issues (except legacy_materials if not deleted)
- [ ] `_safe_extract` function implemented
- [ ] `_is_safe_path` function implemented
- [ ] All tests pass
- [ ] Security scan passes: `bandit -r . -ll`
