# Split BenchmarkController God object

## Problem

`BenchmarkController` in `lb_controller/engine/controller.py` is a **God object** with:

- **23 methods** (flag: `many_methods`)
- **8 constructor parameters** (flag: `init_too_many_params`)
- **Mixed responsibilities**: orchestration + state management + setup + teardown + UI callbacks

This violates the Single Responsibility Principle and makes the class:
1. Hard to test in isolation
2. Hard to understand and modify
3. Prone to bugs when changing one responsibility

## Evidence

**Hotspots report** (`arch_report/hotspots_lb_controller.txt`):
```
lb_controller/engine/controller.py:BenchmarkController | methods=23 init_params=8 imports=9 flags=['name_suggests_orchestrator', 'many_methods', 'init_too_many_params']
```

**Current responsibilities mixed in one class**:
1. **State management** - `_transition()`, `_arm_stop()`, `_stop_requested()`
2. **Setup coordination** - `_run_global_setup()`
3. **Workload orchestration** - `_run_workloads()`, `_process_single_workload()`
4. **Teardown coordination** - `_run_global_teardown()`
5. **Stop protocol** - `_handle_stop_protocol()`, `_handle_stop_during_workloads()`
6. **UI callbacks** - `_refresh_journal()`, output_formatter
7. **Plugin asset management** - `_get_plugin_assets()`
8. **Summary building** - `_build_summary()`

## Solution

### Target Architecture: Split into focused classes

```
┌─────────────────────────────────────────────────────────────┐
│                    BenchmarkController                       │
│  (Thin orchestrator - delegates to specialized services)    │
│  - run()                                                     │
│  - Coordinates phases                                        │
│  - Holds state machine reference                             │
└─────────────────────────────┬───────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐   ┌─────────────────┐   ┌────────────────┐
│ SetupService  │   │ WorkloadRunner  │   │ TeardownService│
│ (existing)    │   │ (new)           │   │ (new)          │
│ - setup()     │   │ - run_workload()│   │ - teardown()   │
│ - prepare()   │   │ - run_all()     │   │ - cleanup()    │
└───────────────┘   └─────────────────┘   └────────────────┘

┌───────────────────┐   ┌─────────────────────┐
│ StopCoordinator   │   │ UINotifier          │
│ (mostly exists)   │   │ (new)               │
│ - arm_stop()      │   │ - refresh_journal() │
│ - handle_stop()   │   │ - notify_phase()    │
│ - wait_runners()  │   │ - format_output()   │
└───────────────────┘   └─────────────────────┘
```

### Phase 1: Extract WorkloadRunner service

Create `lb_controller/services/workload_runner.py`:

```python
"""Service for running individual workloads."""

from dataclasses import dataclass
from typing import Dict, List, Optional, Callable

from lb_controller.models.state import ControllerStateMachine
from lb_runner.models.config import BenchmarkConfig, WorkloadConfig


@dataclass
class WorkloadRunContext:
    """Context for a workload run."""
    test_name: str
    workload_cfg: WorkloadConfig
    pending_hosts: List[str]
    pending_reps: List[int]
    state: "RunState"


class WorkloadRunner:
    """Runs individual workloads with proper isolation."""

    def __init__(
        self,
        config: BenchmarkConfig,
        executor: "AnsibleRunnerExecutor",
        state_machine: ControllerStateMachine,
    ):
        self.config = config
        self.executor = executor
        self.state_machine = state_machine

    def run_single_workload(
        self,
        ctx: WorkloadRunContext,
        phases: Dict[str, "ExecutionResult"],
        ui_log: Callable[[str], None],
    ) -> bool:
        """Run a single workload. Returns True if should continue."""
        # Move logic from BenchmarkController._process_single_workload()
        pass

    def run_workload_setup(self, ctx: WorkloadRunContext) -> None:
        """Run setup for a workload."""
        # Move from BenchmarkController._run_workload_setup()
        pass

    def run_workload_execution(self, ctx: WorkloadRunContext) -> None:
        """Execute the workload."""
        # Move from BenchmarkController._run_workload_execution()
        pass
```

### Phase 2: Extract TeardownService

Create `lb_controller/services/teardown_service.py`:

```python
"""Service for teardown operations."""

class TeardownService:
    """Handles teardown and cleanup operations."""

    def __init__(self, executor: "AnsibleRunnerExecutor"):
        self.executor = executor

    def run_global_teardown(
        self,
        state: "RunState",
        phases: Dict[str, "ExecutionResult"],
        ui_log: Callable[[str], None],
    ) -> None:
        """Run global teardown playbook."""
        # Move from playbooks.run_global_teardown()
        pass

    def cleanup_workload(self, workload_name: str) -> None:
        """Cleanup after a specific workload."""
        pass
```

### Phase 3: Extract UINotifier

Create `lb_controller/services/ui_notifier.py`:

```python
"""Service for UI notifications."""

class UINotifier:
    """Handles UI updates and journal refresh."""

    def __init__(
        self,
        output_formatter: Optional["OutputFormatter"] = None,
        journal_refresh: Optional[Callable[[], None]] = None,
    ):
        self.output_formatter = output_formatter
        self._journal_refresh = journal_refresh

    def notify_phase(self, phase: str) -> None:
        """Notify UI of phase change."""
        if self.output_formatter:
            self.output_formatter.set_phase(phase)

    def refresh_journal(self) -> None:
        """Trigger journal refresh."""
        if self._journal_refresh:
            try:
                self._journal_refresh()
            except Exception:
                pass

    def log(self, message: str) -> None:
        """Log message to UI."""
        pass
```

### Phase 4: Simplify BenchmarkController

After extraction, controller becomes thin:

```python
class BenchmarkController:
    """Orchestrates benchmark execution by delegating to services."""

    def __init__(
        self,
        config: BenchmarkConfig,
        executor: AnsibleRunnerExecutor,
        # Fewer params - services injected or created internally
    ):
        self.config = config
        self.executor = executor
        self.state_machine = ControllerStateMachine()

        # Create services
        self.setup_service = SetupService(executor)
        self.workload_runner = WorkloadRunner(config, executor, self.state_machine)
        self.teardown_service = TeardownService(executor)
        self.ui_notifier = UINotifier()

    def run(self, test_types: List[str], run_id: Optional[str] = None) -> RunExecutionSummary:
        """Main orchestration - delegates to services."""
        state = self._prepare_run_state(test_types, run_id)

        # Setup phase
        self.setup_service.run_global_setup(state)

        # Workload phase
        for test_name in test_types:
            self.workload_runner.run_single_workload(test_name, state)

        # Teardown phase
        self.teardown_service.run_global_teardown(state)

        return self._build_summary(state)
```

## Implementation Steps

### Step 1: Add characterization tests
```bash
# Create tests that capture current behavior
uv run pytest tests/unit/lb_controller/ -v --cov=lb_controller
```

### Step 2: Extract WorkloadRunner (lowest risk)
```python
# Create lb_controller/services/workload_runner.py
# Move _run_workloads, _process_single_workload, etc.
```

### Step 3: Run tests after each extraction
```bash
uv run pytest tests/unit/lb_controller/ tests/integration/ -v
```

### Step 4: Extract TeardownService

### Step 5: Extract UINotifier

### Step 6: Simplify BenchmarkController constructor

## Risk Assessment

| Aspect | Level | Notes |
|--------|-------|-------|
| Risk | **High** | Central class, many dependencies |
| Effort | **High** | ~8 hours |
| Validation | Unit + Integration + E2E tests |

## Acceptance Criteria

- [ ] `WorkloadRunner` service created
- [ ] `TeardownService` created
- [ ] `UINotifier` created
- [ ] `BenchmarkController` has <15 methods
- [ ] `BenchmarkController.__init__` has <5 parameters
- [ ] All existing tests pass
- [ ] No regression in E2E tests
