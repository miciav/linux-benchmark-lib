# DFAAS-QUALITY-4: Reduce environment variable coupling

## Context
The `DfaasGenerator` reads multiple environment variables directly, creating implicit dependencies that make testing difficult and coupling to the execution environment.

## Goal
Encapsulate runtime context in an injectable dataclass, reducing direct environment variable access.

## Scope
- Create ExecutionContext dataclass
- Inject context instead of reading env vars
- Provide factory for env-based context creation
- Maintain backward compatibility

## Non-scope
- Changing what information is available
- Removing environment variables entirely
- Configuration file changes

## Current State

### Environment Variables Read in generator.py
```python
# _resolve_run_id()
os.environ.get("LB_RUN_HOST")

# _ensure_event_context()
os.environ.get("LB_RUN_HOST")
os.environ.get("LB_RUN_REPETITION")
os.environ.get("LB_RUN_TOTAL_REPS")

# _emit_log_event()
os.environ.get("LB_ENABLE_EVENT_LOGGING")

# _run_k6()
os.environ.get("LB_RUN_HOST")
```

### async_localrunner.py
```python
_env("LB_RUN_WORKLOAD")
_env("LB_RUN_REPETITION")
_env("LB_RUN_TOTAL_REPS")
os.environ.get("LB_RUN_ID", "")
os.environ.get("LB_RUN_HOST", "")
os.environ.get("LB_BENCH_CONFIG_PATH", "...")
os.environ.get("LB_RUN_STOP_FILE", "STOP")
_env("LB_EVENT_STREAM_PATH")
os.environ.get("LB_RUN_STATUS_PATH")
os.environ.get("LB_RUN_DAEMONIZE")
_env("LB_RUN_PID_PATH")
```

Problems:
1. 10+ environment variables read directly
2. Testing requires monkeypatching os.environ
3. Implicit dependencies not visible in signatures
4. Duplication of env var names across files

## Proposed Design

### ExecutionContext Dataclass
```python
# lb_plugins/plugins/dfaas/context.py

@dataclass
class ExecutionContext:
    """Runtime context for DFaaS generator execution."""
    run_id: str
    host: str
    workload: str
    repetition: int
    total_repetitions: int
    event_logging_enabled: bool
    config_path: Path
    stop_file_path: Path
    event_stream_path: Path | None
    status_path: Path | None
    pid_path: Path | None
    daemonize: bool

    @classmethod
    def from_environment(cls) -> 'ExecutionContext':
        """Factory method to create context from environment variables."""
        return cls(
            run_id=os.environ.get("LB_RUN_ID", ""),
            host=os.environ.get("LB_RUN_HOST", "") or os.uname().nodename,
            workload=os.environ.get("LB_RUN_WORKLOAD", "dfaas"),
            repetition=int(os.environ.get("LB_RUN_REPETITION", "1")),
            total_repetitions=int(os.environ.get("LB_RUN_TOTAL_REPS", "1")),
            event_logging_enabled=os.environ.get("LB_ENABLE_EVENT_LOGGING") == "1",
            config_path=Path(os.environ.get("LB_BENCH_CONFIG_PATH", "benchmark_config.generated.json")),
            stop_file_path=Path(os.environ.get("LB_RUN_STOP_FILE", "STOP")),
            event_stream_path=Path(os.environ["LB_EVENT_STREAM_PATH"]) if "LB_EVENT_STREAM_PATH" in os.environ else None,
            status_path=Path(os.environ["LB_RUN_STATUS_PATH"]) if "LB_RUN_STATUS_PATH" in os.environ else None,
            pid_path=Path(os.environ["LB_RUN_PID_PATH"]) if "LB_RUN_PID_PATH" in os.environ else None,
            daemonize=os.environ.get("LB_RUN_DAEMONIZE") == "1",
        )

    @classmethod
    def for_testing(
        cls,
        run_id: str = "test-run",
        host: str = "test-host",
        **kwargs
    ) -> 'ExecutionContext':
        """Factory method for testing with sensible defaults."""
        return cls(
            run_id=run_id,
            host=host,
            workload=kwargs.get("workload", "dfaas"),
            repetition=kwargs.get("repetition", 1),
            total_repetitions=kwargs.get("total_repetitions", 1),
            event_logging_enabled=kwargs.get("event_logging_enabled", False),
            config_path=kwargs.get("config_path", Path("test_config.json")),
            stop_file_path=kwargs.get("stop_file_path", Path("STOP")),
            event_stream_path=kwargs.get("event_stream_path"),
            status_path=kwargs.get("status_path"),
            pid_path=kwargs.get("pid_path"),
            daemonize=kwargs.get("daemonize", False),
        )
```

### Generator Update
```python
class DfaasGenerator(BaseGenerator):
    def __init__(
        self,
        config: DfaasConfig,
        name: str = "DfaasGenerator",
        context: ExecutionContext | None = None,
    ):
        super().__init__(name)
        self.config = config
        self._context = context or ExecutionContext.from_environment()

    def _emit_log_event(self, message: str, *, level: str = "INFO") -> None:
        if not self._context.event_logging_enabled:
            return
        # Use self._context.run_id, self._context.host, etc.
```

### async_localrunner.py Update
```python
def main() -> int:
    try:
        context = ExecutionContext.from_environment()
    except Exception as exc:
        sys.stderr.write(f"{exc}\n")
        return 2

    # Use context.workload, context.repetition, etc.
```

## Partial Objectives + Tests

### Objective 1: Create ExecutionContext dataclass
Define with factory methods.
**Tests**:
- Unit test: `test_context_from_environment`
- Unit test: `test_context_for_testing`
- Unit test: `test_context_defaults`

### Objective 2: Update DfaasGenerator
Inject context, remove direct env access.
**Tests**:
- Unit test: generator uses injected context
- Unit test: generator creates context if not provided

### Objective 3: Update async_localrunner
Use ExecutionContext factory.
**Tests**:
- Unit test: context created from env
- Integration test: runner works with context

### Objective 4: Update tests
Use `ExecutionContext.for_testing()`.
**Tests**:
- All existing tests pass
- No more `monkeypatch.setenv` for common vars

## Acceptance Criteria
- [ ] ExecutionContext encapsulates all runtime context
- [ ] Generator accepts optional context injection
- [ ] Factory methods for production and testing
- [ ] All existing tests pass
- [ ] Reduced env var coupling in generator

## Files to Create
- `lb_plugins/plugins/dfaas/context.py`
- `tests/unit/lb_plugins/test_dfaas_context.py`

## Files to Modify
- `lb_plugins/plugins/dfaas/generator.py`
- `lb_runner/services/async_localrunner.py`
- Test files using env var mocking

## Dependencies
- 017 (error handling complete)

## Effort
~3 hours

