# DFAAS-REFACTOR-4: Decompose _run_command() method

## Context
The `_run_command()` method in `DfaasGenerator` is a 150-line "god method" that handles the entire benchmark execution flow, making it difficult to understand, test, and maintain.

## Goal
Decompose `_run_command()` into smaller, focused methods with clear responsibilities.

## Scope
- Split into logical phases
- Improve readability
- Maintain exact same behavior
- Enable better unit testing

## Non-scope
- Changing execution logic
- Adding new features
- Performance optimization

## Current State
`_run_command()` (lines 317-459) handles:
1. Configuration enumeration
2. Query loading
3. Index loading
4. Base idle measurement
5. Configuration loop:
   - Dominance check
   - Index check
   - Script generation
   - Iteration loop:
     - Cooldown wait
     - k6 execution
     - Summary parsing
     - Metrics collection
     - Result building
     - Overload tracking
   - Index update
6. Result aggregation

This is too many responsibilities for a single method.

## Proposed Design

### Method Decomposition
```python
class DfaasGenerator(BaseGenerator):
    def _run_command(self) -> None:
        """Main entry point - orchestrates phases."""
        context = self._prepare_run()
        results = self._execute_configs(context)
        self._finalize_results(results)

    def _prepare_run(self) -> RunContext:
        """Phase 1: Setup and initialization."""
        # Load queries, index, measure baseline
        return RunContext(...)

    def _execute_configs(self, context: RunContext) -> ExecutionResults:
        """Phase 2: Execute all configurations."""
        for config in context.configs:
            if self._should_skip(config, context):
                continue
            self._execute_single_config(config, context)
        return context.results

    def _execute_single_config(
        self,
        config: ConfigPairs,
        context: RunContext,
    ) -> None:
        """Execute one configuration with all iterations."""
        for iteration in range(1, self.config.iterations + 1):
            self._execute_iteration(config, iteration, context)

    def _execute_iteration(
        self,
        config: ConfigPairs,
        iteration: int,
        context: RunContext,
    ) -> IterationResult:
        """Execute a single iteration of a configuration."""
        # Cooldown, k6 run, metrics, result building
        ...

    def _should_skip(self, config: ConfigPairs, context: RunContext) -> bool:
        """Check if config should be skipped."""
        # Dominance and index checks
        ...

    def _finalize_results(self, results: ExecutionResults) -> None:
        """Phase 3: Build final result dictionary."""
        self._result = {...}
```

### Data Classes
```python
@dataclass
class RunContext:
    output_dir: Path
    function_names: list[str]
    configs: list[list[tuple[str, int]]]
    queries: dict[str, QueryDefinition]
    existing_index: set[tuple[tuple[str, ...], tuple[int, ...]]]
    base_idle: MetricsSnapshot
    results: ExecutionResults

@dataclass
class ExecutionResults:
    results_rows: list[dict[str, Any]]
    skipped_rows: list[dict[str, Any]]
    index_rows: list[dict[str, Any]]
    summary_entries: list[dict[str, Any]]
    metrics_entries: list[dict[str, Any]]
    script_entries: list[dict[str, Any]]
    overloaded_configs: list[list[tuple[str, int]]]
```

## Partial Objectives + Tests

### Objective 1: Define data classes
Create `RunContext` and `ExecutionResults`.
**Tests**:
- Unit test: dataclass instantiation

### Objective 2: Extract _prepare_run()
Move initialization logic.
**Tests**:
- Unit test: `test_prepare_run_loads_queries`
- Unit test: `test_prepare_run_loads_index`
- Unit test: `test_prepare_run_measures_baseline`

### Objective 3: Extract _should_skip()
Move skip logic.
**Tests**:
- Unit test: `test_should_skip_dominated_config`
- Unit test: `test_should_skip_indexed_config`

### Objective 4: Extract _execute_iteration()
Move single iteration logic.
**Tests**:
- Unit test: `test_execute_iteration_records_result`
- Unit test: `test_execute_iteration_detects_overload`

### Objective 5: Extract _finalize_results()
Move result aggregation.
**Tests**:
- Unit test: `test_finalize_results_builds_dict`

### Objective 6: Wire together
Connect all methods in `_run_command()`.
**Tests**:
- All existing generator tests pass
- Integration test: full run produces same output

## Acceptance Criteria
- [ ] `_run_command()` reduced to ~20 lines
- [ ] Each extracted method has single responsibility
- [ ] All existing tests pass
- [ ] New unit tests for each extracted method
- [ ] Same output produced as before

## Files to Modify
- `lb_plugins/plugins/dfaas/generator.py`

## Files to Create
- Additional test cases in `tests/unit/lb_plugins/test_dfaas_generator.py`

## Dependencies
- 013 (K6Runner)
- 014 (CooldownManager)
- 015 (MetricsCollector)

## Effort
~4 hours

