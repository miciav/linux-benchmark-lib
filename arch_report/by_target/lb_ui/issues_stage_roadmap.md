# Issues - Architecture Refactor Stages

## Issue: Stage 0 - Safety Net and Baseline Fixes

### Description
Stabilize the refactor foundation by fixing the currently failing CLI run test and adding characterization tests around controller/runner orchestration and system-info output. This ensures we can move structure without breaking behavior and provides a minimal regression harness.

### Plan
1. Fix failing unit UI test
   - Reproduce `tests/test_cli.py::test_run_command_exists` failure.
   - Align the test setup with CLI workload selection behavior in `lb_ui/cli/commands/run.py`.
   - Ensure the test sets at least one enabled workload or adjusts the fixture to match defaults.
2. Add controller characterization tests
   - Create a fake `RemoteExecutor` that records playbook calls and returns deterministic `ExecutionResult`.
   - Use a minimal `BenchmarkConfig` with a single host and one workload.
   - Assert journal entries, run phases, and summary payload fields are stable.
3. Add runner characterization tests
   - Create a fake generator and fake collector that return deterministic outputs.
   - Run `LocalRunner.run_benchmark` (or smallest runnable subset) to capture output artifacts.
   - Assert results structure and output directory layout.
4. Snapshot system-info output shape
   - Add tests for `SystemInfo.to_dict()` and `SystemInfo.to_csv_rows()` with known minimal data.
   - Assert keys/sections and row counts to catch accidental schema drift.
5. Validation
   - Run `uv run pytest -m unit_ui` and targeted unit tests for controller/runner/system-info.
   - Update any flaky expectations with deterministic fixtures.

### Acceptance Criteria
- `tests/test_cli.py::test_run_command_exists` passes consistently.
- New tests cover controller orchestration, runner execution skeleton, and system-info serialization.
- CI-safe test suite does not require Ansible, Docker, or external tools.

### Risk
Low. Primarily test and fixture updates.

### Evidence
- `tests/test_cli.py:551`
- `lb_ui/cli/commands/run.py:158`
- `lb_controller/engine/controller.py:72`
- `lb_runner/engine/runner.py:59`
- `lb_runner/services/system_info.py:129`


## Issue: Stage 1 - Low-Risk Structural Refactors

### Description
Reduce multi-concern objects by extracting targeted helpers while preserving external APIs. This includes runner orchestration splitting, Ansible executor separation, plugin discovery isolation, and system-info collector separation.

### Plan
1. Split `LocalRunner` responsibilities
   - Extract run planning and output directory creation into `lb_runner/engine/planning` or a new helper module.
   - Extract collector lifecycle into a `CollectorCoordinator` in `lb_runner/services`.
   - Extract results persistence into a `ResultPersister` in `lb_runner/services`.
   - Keep `LocalRunner` as the orchestrator and delegate to helpers.
2. Split `AnsibleRunnerExecutor`
   - Extract inventory building into `InventoryWriter`.
   - Extract env var assembly into `EnvBuilder`.
   - Extract subprocess execution into a `ProcessRunner` or similar helper.
   - Keep the `RemoteExecutor` API stable and update unit tests.
3. Split plugin discovery vs instantiation
   - Create `lb_plugins/discovery.py` with entrypoint and user-dir loading.
   - Keep `PluginRegistry` as a storage/factory that depends on discovery output.
   - Move packaging/installation code into `lb_plugins/installer.py`.
4. Split system-info collection
   - Move `_collect_*` functions into a collector module.
   - Keep `SystemInfo` dataclasses in a types module.
   - Update call sites to use the collector layer.
5. Validation
   - Run unit tests from Stage 0.
   - Validate CLI `lb run` and `lb plugin list` in headless mode.

### Acceptance Criteria
- External APIs (`lb_runner.api`, `lb_controller.api`, `lb_plugins.api`) remain stable.
- `LocalRunner` and `AnsibleRunnerExecutor` are reduced in size and delegate to helpers.
- Plugin discovery and installation are in separate modules.
- System-info logic is split into collector/type modules with unchanged output.

### Risk
Medium. Changes touch core orchestrators and may surface hidden coupling.

### Evidence
- `lb_runner/engine/runner.py:59`
- `lb_controller/adapters/ansible_runner.py:70`
- `lb_plugins/registry.py:56`
- `lb_plugins/api.py:126`
- `lb_runner/services/system_info.py:186`


## Issue: Stage 2 - Consolidation Refactors

### Description
Consolidate overlapping abstractions in plugins and UI by introducing shared bases/strategies for workload metadata, command generators, and presenters/dashboards. This removes duplication hotspots and clarifies extension points.

### Plan
1. Introduce `SimpleWorkloadPlugin`
   - Add a base class with class attributes for `name`, `description`, and asset paths.
   - Update plugins with identical metadata surfaces to inherit and override minimal details.
   - Ensure `WorkloadPlugin` contract is preserved.
2. Introduce `CommandSpec` and `ResultParser` strategy
   - Create a command generator template in `lb_plugins/base_generator`.
   - Move per-plugin command building and parsing into strategy objects.
   - Update `StressNG`, `DD`, `Sysbench`, `UnixBench`, `Yabs`, `Geekbench` generators.
3. Consolidate UI presenters/dashboards
   - Introduce `PresenterBase` with a configurable output sink.
   - Create `DashboardAdapter` that supports headless and threaded variants.
   - Update `HeadlessPresenter`, `RichPresenter`, and dashboard handles to delegate.
4. Validation
   - Run plugin registry unit tests and plugin list CLI.
   - Run a minimal end-to-end workload (local or controlled remote) to verify command generators.
   - Run unit UI tests for headless and threaded dashboard paths.

### Acceptance Criteria
- Plugin duplication pairs are reduced significantly.
- Command generator behavior is preserved with improved test coverage.
- UI presenter and dashboard duplication removed without behavior regressions.

### Risk
High. Consolidation refactors can introduce subtle behavioral differences.

### Evidence
- `arch_report/duplication_candidates_lb_plugins.txt`
- `arch_report/duplication_candidates_lb_ui.txt`
- `lb_plugins/plugins/stress_ng/plugin.py:90`
- `lb_plugins/plugins/dd/plugin.py:168`
- `lb_ui/tui/system/headless.py:99`
- `lb_ui/tui/adapters/tui_adapter.py:80`
