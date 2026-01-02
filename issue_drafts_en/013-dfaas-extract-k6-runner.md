# DFAAS-REFACTOR-1: Extract K6Runner service

## Context
The `DfaasGenerator` class (966 lines) contains k6-specific logic mixed with orchestration concerns. This violates single responsibility principle and makes testing difficult.

## Goal
Extract k6-related functionality into a dedicated `K6Runner` service class.

## Scope
- Extract k6 script generation
- Extract k6 playbook execution
- Extract SSH log streaming
- Maintain backward compatibility

## Non-scope
- Changing k6 script format
- Modifying Ansible playbooks
- Performance optimization

## Current State
The following methods in `generator.py` handle k6 concerns:
- `build_k6_script()` (lines 150-248) - Script generation
- `parse_k6_summary()` (lines 251-270) - Summary parsing
- `_run_k6()` (lines 756-813) - Playbook execution
- `_start_k6_log_stream()` (lines 866-931) - SSH streaming
- `_stop_k6_log_stream()` (lines 933-947) - Stream cleanup
- `_K6LogStream` dataclass (lines 48-53)

**Total**: ~250 lines of k6-specific code

## Proposed Design

### New File Structure
```
lb_plugins/plugins/dfaas/
├── services/
│   ├── __init__.py
│   └── k6_runner.py      # New: K6Runner class
├── generator.py          # Modified: uses K6Runner
└── ...
```

### K6Runner Interface
```python
@dataclass
class K6RunResult:
    summary: dict[str, Any]
    script: str
    config_id: str
    duration_seconds: float

class K6Runner:
    def __init__(
        self,
        k6_host: str,
        k6_user: str,
        k6_ssh_key: str,
        k6_port: int,
        k6_workspace_root: str,
        gateway_url: str,
        duration: str,
        log_stream_enabled: bool = False,
    ) -> None: ...

    def build_script(
        self,
        config_pairs: list[tuple[str, int]],
        functions: list[DfaasFunctionConfig],
    ) -> tuple[str, dict[str, str]]: ...

    def execute(
        self,
        config_id: str,
        script: str,
        target_name: str,
        run_id: str,
    ) -> K6RunResult: ...

    def parse_summary(
        self,
        summary: dict[str, Any],
        metric_ids: dict[str, str],
    ) -> dict[str, dict[str, float]]: ...
```

### Generator Changes
```python
class DfaasGenerator(BaseGenerator):
    def __init__(self, config: DfaasConfig, name: str = "DfaasGenerator"):
        super().__init__(name)
        self.config = config
        self._k6_runner = K6Runner(
            k6_host=config.k6_host,
            k6_user=config.k6_user,
            k6_ssh_key=config.k6_ssh_key,
            k6_port=config.k6_port,
            k6_workspace_root=config.k6_workspace_root,
            gateway_url=config.gateway_url,
            duration=config.duration,
            log_stream_enabled=config.k6_log_stream,
        )
```

## Partial Objectives + Tests

### Objective 1: Create K6Runner class
Move k6 script generation logic.
**Tests**:
- Unit test: `test_k6_runner_builds_valid_script`
- Unit test: `test_k6_runner_script_includes_scenarios`

### Objective 2: Move execution logic
Move playbook execution and SSH streaming.
**Tests**:
- Unit test: `test_k6_runner_execute_calls_ansible` (mocked)
- Unit test: `test_k6_runner_starts_log_stream` (mocked)

### Objective 3: Move summary parsing
Move `parse_k6_summary` to K6Runner.
**Tests**:
- Unit test: `test_k6_runner_parses_summary` (existing test adapted)

### Objective 4: Update generator
Replace direct calls with K6Runner delegation.
**Tests**:
- Existing generator tests still pass
- Integration test: full run with K6Runner

## Acceptance Criteria
- [ ] K6Runner class handles all k6 concerns
- [ ] Generator delegates to K6Runner
- [ ] All existing tests pass
- [ ] New unit tests for K6Runner
- [ ] generator.py reduced by ~250 lines

## Files to Create
- `lb_plugins/plugins/dfaas/services/__init__.py`
- `lb_plugins/plugins/dfaas/services/k6_runner.py`
- `tests/unit/lb_plugins/test_dfaas_k6_runner.py`

## Files to Modify
- `lb_plugins/plugins/dfaas/generator.py`

## Dependencies
- 011, 012 (stabilization complete)

## Effort
~4 hours

