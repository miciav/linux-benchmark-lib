# Reduce complexity hotspots in plugins

## Problem

Several functions have **extreme cyclomatic complexity** (rank D-E), making them:

1. Hard to understand and maintain
2. Prone to bugs
3. Difficult to test thoroughly

## Evidence

**Xenon complexity violations** (`arch_report/xenon.txt`):

| Location | Function | Rank | Severity |
|----------|----------|------|----------|
| `phoronix_test_suite/plugin.py:528` | `_load_manifest` | **E** | Critical |
| `phoronix_test_suite/plugin.py:247` | `_run_command` | **D** | High |
| `geekbench/plugin.py:231` | `_prepare_geekbench` | **D** | High |
| `geekbench/plugin.py:393` | `export_results_to_csv` | **D** | High |
| `geekbench/plugin.py:164` | `_run_command` | **C** | Medium |
| `geekbench/plugin.py:144` | `_after_run` | **C** | Medium |
| `installer.py:48` | `package` | **C** | Medium |
| `installer.py:128` | `_install_directory` | **C** | Medium |

## Solution

### 1. Refactor `PhoronixGenerator._load_manifest` (Rank E → A)

**Current problem**: Massive function parsing XML manifest with many nested conditions.

**Solution**: Extract parser class with strategy pattern.

```python
# Before (in plugin.py, ~100 lines)
def _load_manifest(self, manifest_path: Path) -> Dict[str, Any]:
    # 100+ lines of XML parsing with nested ifs
    ...

# After
class ManifestParser:
    """Parses PTS manifest files."""

    def parse(self, manifest_path: Path) -> ManifestData:
        root = self._load_xml(manifest_path)
        return ManifestData(
            title=self._extract_title(root),
            version=self._extract_version(root),
            arguments=self._extract_arguments(root),
            results=self._extract_results(root),
        )

    def _load_xml(self, path: Path) -> ElementTree:
        ...

    def _extract_title(self, root: ElementTree) -> str:
        ...

    def _extract_arguments(self, root: ElementTree) -> List[Argument]:
        ...

# In plugin.py
def _load_manifest(self, manifest_path: Path) -> Dict[str, Any]:
    parser = ManifestParser()
    data = parser.parse(manifest_path)
    return data.to_dict()
```

### 2. Refactor `PhoronixGenerator._run_command` (Rank D → B)

**Current problem**: Complex error handling and retry logic mixed with execution.

**Solution**: Extract error handler and use command executor pattern.

```python
# Before
def _run_command(self, cmd, timeout, retries=3):
    for attempt in range(retries):
        try:
            # Complex subprocess logic
            # Complex error handling
            # Complex output parsing
        except TimeoutError:
            if attempt < retries - 1:
                # retry logic
            else:
                # final error handling
        except SubprocessError:
            # different error handling
    ...

# After
class CommandExecutor:
    """Executes commands with retry and error handling."""

    def __init__(self, max_retries: int = 3, timeout: int = 300):
        self.max_retries = max_retries
        self.timeout = timeout

    def execute(self, cmd: List[str]) -> CommandResult:
        for attempt in range(self.max_retries):
            result = self._try_execute(cmd, attempt)
            if result.success:
                return result
        return result  # Last failed attempt

    def _try_execute(self, cmd: List[str], attempt: int) -> CommandResult:
        try:
            return self._run_subprocess(cmd)
        except TimeoutError:
            return CommandResult(success=False, error="timeout")
        except SubprocessError as e:
            return CommandResult(success=False, error=str(e))
```

### 3. Refactor `GeekbenchGenerator._prepare_geekbench` (Rank D → B)

**Current problem**: Multiple platform checks and download logic mixed.

**Solution**: Extract platform detector and downloader.

```python
# Before
def _prepare_geekbench(self):
    # Check platform
    if platform.system() == "Linux":
        if platform.machine() == "x86_64":
            url = "..."
        elif platform.machine() == "aarch64":
            url = "..."
    # Download
    # Extract
    # Verify
    ...

# After
class GeekbenchInstaller:
    """Handles Geekbench installation."""

    URLS = {
        ("Linux", "x86_64"): "...",
        ("Linux", "aarch64"): "...",
    }

    def install(self) -> Path:
        url = self._get_download_url()
        archive = self._download(url)
        return self._extract(archive)

    def _get_download_url(self) -> str:
        key = (platform.system(), platform.machine())
        if key not in self.URLS:
            raise UnsupportedPlatformError(key)
        return self.URLS[key]
```

### 4. Refactor `export_results_to_csv` functions (Rank D → A)

**Current problem**: Duplicate complex CSV export logic in multiple plugins.

**Solution**: Extract to shared utility (covered in issue #003).

```python
# Create lb_plugins/utils/csv_export.py
from typing import List, Dict, Any
from pathlib import Path
import csv

def export_results(
    results: List[Dict[str, Any]],
    output_path: Path,
    column_mapping: Dict[str, str],
) -> None:
    """Generic CSV export for benchmark results."""
    columns = list(column_mapping.values())

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()

        for result in results:
            row = {
                column_mapping[k]: v
                for k, v in result.items()
                if k in column_mapping
            }
            writer.writerow(row)
```

### 5. Refactor `PluginInstaller.package` (Rank C → A)

**Current problem**: Multiple archive type checks and handling.

**Solution**: Strategy pattern for archive handlers.

```python
# Before
def package(self, source: str) -> str:
    if source.endswith(".zip"):
        # zip handling
    elif source.endswith(".tar.gz"):
        # tar.gz handling
    elif source.endswith(".whl"):
        # wheel handling
    elif os.path.isdir(source):
        # directory handling
    ...

# After
class ArchiveHandler(Protocol):
    def can_handle(self, source: str) -> bool: ...
    def extract(self, source: str, dest: Path) -> None: ...

class ZipHandler(ArchiveHandler):
    def can_handle(self, source: str) -> bool:
        return source.endswith(".zip")

    def extract(self, source: str, dest: Path) -> None:
        with zipfile.ZipFile(source) as zf:
            zf.extractall(dest)

class PluginInstaller:
    handlers: List[ArchiveHandler] = [ZipHandler(), TarHandler(), WheelHandler()]

    def package(self, source: str) -> str:
        handler = self._get_handler(source)
        return handler.extract(source, self.dest)

    def _get_handler(self, source: str) -> ArchiveHandler:
        for handler in self.handlers:
            if handler.can_handle(source):
                return handler
        raise UnsupportedArchiveError(source)
```

## Implementation Steps

### Step 1: Add characterization tests for complex functions
```bash
# Capture current behavior before refactoring
uv run pytest tests/unit/lb_plugins/test_phoronix*.py -v
uv run pytest tests/unit/lb_plugins/test_geekbench*.py -v
```

### Step 2: Refactor one function at a time

### Step 3: Run xenon after each refactor
```bash
uv run xenon lb_plugins --max-average=B --max-modules=C --max-absolute=C
```

### Step 4: Run full test suite
```bash
uv run pytest tests/unit/lb_plugins/ -v
```

## Risk Assessment

| Function | Risk | Notes |
|----------|------|-------|
| `_load_manifest` | **Medium** | Complex parsing, need good test coverage |
| `_run_command` | **Medium** | Error handling critical |
| `_prepare_geekbench` | **Low** | Mostly download logic |
| `export_results_to_csv` | **Low** | Pure function, easy to test |
| `package` | **Medium** | Many edge cases |

## Acceptance Criteria

- [ ] All rank E functions reduced to rank C or better
- [ ] All rank D functions reduced to rank B or better
- [ ] `ManifestParser` class created for PTS
- [ ] `CommandExecutor` class created (or reuse existing)
- [ ] `GeekbenchInstaller` class created
- [ ] All plugin tests pass
- [ ] Xenon passes with `--max-absolute=C`
