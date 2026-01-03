# Consolidate plugin duplication - use SimpleWorkloadPlugin

## Problem

There is **massive code duplication** across workload plugins. Analysis found:

- **5 plugin pairs with 100% method similarity**
- **30+ pairs with >80% similarity**
- All plugins implement the same 9 methods with nearly identical code

This duplication:
1. **Increases maintenance burden** - changes must be made in 10+ places
2. **Introduces bugs** - inconsistent implementations across plugins
3. **Violates DRY** - same code copy-pasted everywhere

## Evidence

**Duplication candidates** (`arch_report/duplication_candidates_lb_plugins.txt`):

### 100% Similarity Pairs (Identical)
| Plugin A | Plugin B | Common Methods |
|----------|----------|----------------|
| StressNGPlugin | DDPlugin | config_cls, create_generator, description, get_ansible_setup_path, get_ansible_teardown_path, get_preset_config, get_required_apt_packages, get_required_local_tools, name |
| FIOPlugin | StreamPlugin | Same 9 methods |
| FIOPlugin | HPLPlugin | Same 9 methods |
| StreamPlugin | HPLPlugin | Same 9 methods |
| YabsPlugin | GeekbenchPlugin | Same 10 methods |

### Generator Duplication (89% Similarity)
| Generator A | Generator B | Common Methods |
|-------------|-------------|----------------|
| UnixBenchGenerator | SysbenchGenerator | `__init__`, `_build_command`, `_log_failure`, `_popen_kwargs`, `_timeout_seconds`, `_validate_environment` |
| StressNGGenerator | DDGenerator | Same 6 methods |

## Root Cause

`SimpleWorkloadPlugin` exists but is **underutilized**. Most plugins extend `WorkloadPlugin` directly instead of using the simpler base class.

```python
# Current (duplicated)
class StressNGPlugin(WorkloadPlugin):
    @property
    def name(self) -> str:
        return "stress_ng"

    @property
    def config_cls(self) -> Type[BasePluginConfig]:
        return StressNGConfig

    def create_generator(self, config, output_dir, run_id) -> BaseGenerator:
        return StressNGGenerator(config, output_dir, run_id)

    # ... 6 more nearly identical methods

# Should be (using SimpleWorkloadPlugin)
class StressNGPlugin(SimpleWorkloadPlugin):
    _name = "stress_ng"
    _description = "stress-ng workload generator"
    _config_cls = StressNGConfig
    _generator_cls = StressNGGenerator
    _ansible_setup_path = "ansible/setup.yml"
```

## Solution

### Phase 1: Migrate simple plugins to SimpleWorkloadPlugin

**Target plugins** (100% similarity, easiest to migrate):
1. `StressNGPlugin` → `SimpleWorkloadPlugin`
2. `DDPlugin` → `SimpleWorkloadPlugin`
3. `FIOPlugin` → `SimpleWorkloadPlugin`
4. `StreamPlugin` → `SimpleWorkloadPlugin`
5. `HPLPlugin` → `SimpleWorkloadPlugin`
6. `UnixBenchPlugin` → `SimpleWorkloadPlugin`
7. `SysbenchPlugin` → `SimpleWorkloadPlugin`

**Migration template**:
```python
# Before (verbose)
class DDPlugin(WorkloadPlugin):
    @property
    def name(self) -> str:
        return "dd"

    @property
    def description(self) -> str:
        return "dd disk benchmark"

    @property
    def config_cls(self) -> Type[BasePluginConfig]:
        return DDConfig

    def create_generator(self, config, output_dir, run_id):
        return DDGenerator(config, output_dir, run_id)

    def get_ansible_setup_path(self) -> Optional[Path]:
        return Path(__file__).parent / "ansible" / "setup.yml"

    def get_required_apt_packages(self) -> List[str]:
        return []

    def get_required_local_tools(self) -> List[str]:
        return ["dd"]

    def get_preset_config(self, intensity: WorkloadIntensity):
        return DDConfig()

# After (concise)
class DDPlugin(SimpleWorkloadPlugin):
    _name = "dd"
    _description = "dd disk benchmark"
    _config_cls = DDConfig
    _generator_cls = DDGenerator
    _ansible_setup_path = "ansible/setup.yml"
    _required_local_tools = ["dd"]
```

### Phase 2: Extract CommandGeneratorMixin

Create a mixin for shared generator logic:

```python
# lb_plugins/base_generator.py

class CommandGeneratorMixin:
    """Mixin providing common subprocess execution logic."""

    def _log_failure(self, cmd: List[str], returncode: int, stderr: str) -> None:
        logger.error("Command failed: %s (rc=%d)", " ".join(cmd), returncode)
        if stderr:
            logger.error("stderr: %s", stderr[:500])

    def _popen_kwargs(self) -> Dict[str, Any]:
        return {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
        }

    def _validate_environment(self) -> None:
        """Override to add validation logic."""
        pass
```

### Phase 3: Extract CSV export utility

Create shared utility for `export_results_to_csv`:

```python
# lb_plugins/utils/csv_export.py

def export_benchmark_results_to_csv(
    results: List[Dict[str, Any]],
    output_path: Path,
    columns: List[str],
) -> None:
    """Export benchmark results to CSV format."""
    import csv
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(results)
```

## Implementation Steps

### Step 1: Enhance SimpleWorkloadPlugin if needed
```bash
# Check current implementation
cat lb_plugins/interface.py | grep -A 50 "class SimpleWorkloadPlugin"
```

### Step 2: Migrate DDPlugin as pilot
```python
# Edit lb_plugins/plugins/dd/plugin.py
```

### Step 3: Run tests
```bash
uv run pytest tests/unit/lb_plugins/test_dd*.py -v
```

### Step 4: Migrate remaining plugins one by one

### Step 5: Run full plugin test suite
```bash
uv run pytest tests/unit/lb_plugins/ -v
```

## Risk Assessment

| Aspect | Level | Notes |
|--------|-------|-------|
| Risk | **Medium** | Changing plugin base classes |
| Effort | **Medium** | ~4 hours for all plugins |
| Validation | Full plugin test suite |

## Acceptance Criteria

- [ ] At least 7 plugins migrated to `SimpleWorkloadPlugin`
- [ ] `CommandGeneratorMixin` created and used
- [ ] `export_benchmark_results_to_csv` utility created
- [ ] All plugin tests pass
- [ ] Duplication analysis shows <50% similarity for migrated plugins
