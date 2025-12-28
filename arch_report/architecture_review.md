# Architecture Review

## Executive Summary
- Duplication is concentrated in `lb_plugins` (51 pairs) and `lb_ui` (6 pairs) while `lb_controller`/`lb_runner` show none, pointing to plugins/UI as the primary unification targets; evidence: `arch_report/duplication_candidates_lb_plugins.txt`, `arch_report/duplication_candidates_lb_ui.txt`, `arch_report/duplication_candidates_lb_controller.txt`, `arch_report/duplication_candidates_lb_runner.txt`, `lb_plugins/plugins/stress_ng/plugin.py:90`, `lb_plugins/plugins/dd/plugin.py:168`.
- Core orchestration is dominated by God objects in controller and runner, increasing coupling and change risk; evidence: `arch_report/hotspots_lb_controller.txt`, `lb_controller/engine/controller.py:72`, `arch_report/hotspots_lb_runner.txt`, `lb_runner/engine/runner.py:59`.
- Plugin registry/installer mix discovery, config instantiation, and filesystem/packaging concerns, which obscures boundaries; evidence: `arch_report/hotspots_lb_plugins.txt`, `lb_plugins/registry.py:56`, `lb_plugins/api.py:126`.
- UI selection/picker logic is a complexity hotspot (C/E ranks) and will be brittle for UX changes without decomposition; evidence: `arch_report/by_target/lb_ui/xenon.txt`, `lb_ui/flows/selection.py:20`, `lb_ui/tui/system/components/picker.py:242`.
- System info collection mixes data model, subprocess IO, and serialization with D/C complexity ranks; evidence: `arch_report/by_target/lb_runner/xenon.txt`, `lb_runner/services/system_info.py:112`, `lb_runner/services/system_info.py:148`.
- The current test/coverage baseline is blocked by `test_run_command_exists`, reducing refactor safety; evidence: `arch_report/by_target/lb_runner/pytest_cov.txt`, `tests/test_cli.py:551`.
- Dependency hygiene shows unused extras and missing `controller_stop_runner`, indicating drift between boundaries and declared deps; evidence: `arch_report/by_target/lb_runner/deptry.txt`, `pyproject.toml:24`, `pyproject.toml:33`.
- Import cycle detection failed due to grimp Project lookup errors, so cycle status is unknown; evidence: `arch_report/by_target/lb_ui/grimp_cycles.txt`, `arch_report/by_target/lb_controller/grimp_cycles.txt`.
- Dynamic imports and shell usage in collectors are flagged by semgrep/bandit, so plugin/collector execution boundaries need hardening; evidence: `arch_report/by_target/lb_runner/semgrep_auto.txt`, `lb_runner/metric_collectors/__init__.py:21`, `arch_report/by_target/lb_runner/bandit.txt`, `lb_runner/metric_collectors/cli_collector.py:36`.

## Current Architecture Map
- Package roles are documented as runner/controller/app/UI/analytics/plugins/provisioner/common; evidence: `README.md:108`, `README.md:112`, `README.md:119`.
- CLI entrypoints are `lb` and `lb-ui` and route to `lb_ui.cli.main:main`; evidence: `pyproject.toml:71`, `pyproject.toml:72`.
- CLI is Typer-based with subcommand wiring; evidence: `lb_ui/cli/main.py:13`, `lb_ui/cli/main.py:42`.
- Core run flow is CLI -> app services -> controller -> runner -> plugin registry -> analytics; evidence: `lb_ui/cli/commands/run.py:41`, `lb_app/services/run_service.py:1`, `lb_controller/engine/controller.py:72`, `lb_runner/engine/runner.py:59`, `lb_plugins/registry.py:56`, `lb_analytics/api.py:1`.
- Stable API surfaces are exposed via package `api.py` facades; evidence: `lb_app/api.py:1`, `lb_controller/api.py:1`, `lb_runner/api.py:1`.
- Targets audited by size were `lb_ui`, `lb_controller`, `lb_plugins`, `lb_runner`; per-target outputs are in `arch_report/by_target/...`.

## Evidence Tables

### 3.1 Cycles and Dependency Issues
- Import cycle analysis is unavailable because grimp cannot locate Project across targets; evidence: `arch_report/by_target/lb_ui/grimp_cycles.txt`, `arch_report/by_target/lb_controller/grimp_cycles.txt`, `arch_report/by_target/lb_plugins/grimp_cycles.txt`, `arch_report/by_target/lb_runner/grimp_cycles.txt`.
- Controller depends directly on plugins and runner APIs, tightening layer coupling; evidence: `lb_controller/engine/controller.py:15`, `lb_controller/engine/controller.py:16`, `lb_controller/engine/controller.py:87`.
- `lb_app.api` is a wide facade reexporting multiple layers, which risks accidental cross-layer usage; evidence: `lb_app/api.py:1`, `lb_app/api.py:28`, `lb_app/api.py:35`.

### 3.2 Duplication Candidates
- `_HeadlessPresenter` <-> `RichPresenter` (sim=1.00, same `info/warning/error/success/panel/rule` surface); action: introduce a shared `PresenterBase` or `MessageFormatter` with sink adapters; risk: Low; validate with UI unit tests; evidence: `arch_report/duplication_candidates_lb_ui.txt`, `lb_ui/tui/system/headless.py:99`, `lb_ui/tui/system/components/presenter.py:7`.
- `_HeadlessDashboard` <-> `ThreadedDashboardHandle` <-> `Dashboard` (sim=0.93/0.91/0.85, same dashboard methods); action: build a single `DashboardAdapter` that can be headless or threaded; risk: Low; validate with dashboard smoke tests; evidence: `arch_report/duplication_candidates_lb_ui.txt`, `lb_ui/tui/system/headless.py:139`, `lb_ui/tui/adapters/tui_adapter.py:80`, `lb_ui/tui/system/protocols.py:48`.
- `StressNGPlugin` <-> `DDPlugin` (sim=1.00, same metadata/asset getters); action: introduce a metadata-driven `SimpleWorkloadPlugin` base with class attributes; risk: Medium; validate with plugin registry and `lb plugin list`; evidence: `arch_report/duplication_candidates_lb_plugins.txt`, `lb_plugins/plugins/stress_ng/plugin.py:90`, `lb_plugins/plugins/dd/plugin.py:168`.
- `FIOPlugin` <-> `StreamPlugin` (sim=1.00, same metadata + CSV export hooks); action: shared CSV-export mixin + metadata base; risk: Medium; validate with plugin export tests; evidence: `arch_report/duplication_candidates_lb_plugins.txt`, `lb_plugins/plugins/fio/plugin.py:228`, `lb_plugins/plugins/stream/plugin.py:303`.
- `YabsPlugin` <-> `GeekbenchPlugin` (sim=1.00, same metadata/asset getters); action: metadata base + plug-in specific generators only; risk: Medium; validate with plugin list and config serialization; evidence: `arch_report/duplication_candidates_lb_plugins.txt`, `lb_plugins/plugins/yabs/plugin.py:202`, `lb_plugins/plugins/geekbench/plugin.py:342`.
- `StressNGGenerator` <-> `DDGenerator` (sim=0.82, shared command lifecycle methods); action: introduce `CommandGenerator` template with hooks for build/validate/after_run; risk: Medium; validate with generator unit tests and CLI dry runs; evidence: `arch_report/duplication_candidates_lb_plugins.txt`, `lb_plugins/plugins/stress_ng/plugin.py:32`, `lb_plugins/plugins/dd/plugin.py:34`.

### 3.3 Multi-Concern Hotspots
- `BenchmarkController` mixes config mutation, asset setup, orchestration, journaling, stop coordination, and summary building; decomposition: split `RunPreparer`, `PlaybookOrchestrator`, `RunSummaryBuilder`, `StopCoordinator` integration; evidence: `arch_report/hotspots_lb_controller.txt`, `lb_controller/engine/controller.py:75`, `lb_controller/engine/controller.py:87`, `lb_controller/engine/controller.py:170`.
- `LocalRunner` handles planning, filesystem output, collector lifecycle, plugin execution, and result persistence; decomposition: extract `RunPlanner`, `CollectorCoordinator`, and `ResultPersister` from `lb_runner/engine/runner.py`; evidence: `arch_report/hotspots_lb_runner.txt`, `lb_runner/engine/runner.py:59`, `lb_runner/engine/runner.py:136`, `lb_runner/engine/runner.py:189`.
- `AnsibleRunnerExecutor` combines inventory management, env assembly, subprocess control, and streaming; decomposition: separate `InventoryWriter`, `EnvBuilder`, and `ProcessRunner`; evidence: `arch_report/hotspots_lb_controller.txt`, `lb_controller/adapters/ansible_runner.py:23`, `lb_controller/adapters/ansible_runner.py:70`, `lb_controller/adapters/ansible_runner.py:165`.
- `PluginRegistry` mixes discovery, entrypoint loading, user-dir loading, and config instantiation; decomposition: split `PluginDiscovery` and `PluginFactory` from registry; evidence: `arch_report/hotspots_lb_plugins.txt`, `lb_plugins/registry.py:56`, `lb_plugins/registry.py:86`, `lb_plugins/registry.py:117`.
- `PluginInstaller` handles git/archives/packaging and filesystem operations; decomposition: extract `PluginPackager` and `PluginInstaller` adapters; evidence: `arch_report/hotspots_lb_plugins.txt`, `lb_plugins/api.py:126`, `lb_plugins/api.py:151`, `lb_plugins/api.py:227`.
- `PhoronixTestSuiteWorkloadPlugin` + generator mix command execution, interactive handling, result discovery, and error mapping; decomposition: split command runner, result locator, and parser; evidence: `arch_report/hotspots_lb_plugins.txt`, `lb_plugins/plugins/phoronix_test_suite/plugin.py:258`, `lb_plugins/plugins/phoronix_test_suite/plugin.py:413`.

### 3.4 Complexity Hotspots
- `SystemInfo.to_csv_rows` (rank D) plus `_collect_cpu/_collect_disks/_collect_nics` (rank C) should be split into per-section serializers/collectors; evidence: `arch_report/by_target/lb_runner/xenon.txt`, `lb_runner/services/system_info.py:148`, `lb_runner/services/system_info.py:186`, `lb_runner/services/system_info.py:246`.
- `CLICollector._collect_metrics` and `_parse_sar` (rank C) should be split into command execution and parsing helpers; evidence: `arch_report/by_target/lb_runner/xenon.txt`, `lb_runner/metric_collectors/cli_collector.py:36`, `lb_runner/metric_collectors/cli_collector.py:92`.
- `BenchmarkController._prepare_run_state` (rank C) should be extracted to a `RunStateBuilder`; evidence: `arch_report/by_target/lb_controller/xenon.txt`, `lb_controller/engine/controller.py:197`.
- `AnsibleRunnerExecutor.run_playbook` (rank C) should split inventory/env setup from execution; evidence: `arch_report/by_target/lb_controller/xenon.txt`, `lb_controller/adapters/ansible_runner.py:70`.
- `select_workloads_interactively` (rank E) should move data shaping into a view-model service; evidence: `arch_report/by_target/lb_ui/xenon.txt`, `lb_ui/flows/selection.py:20`.
- `picker._toggle_selection/_preview_panel` (rank C) should separate selection state from rendering; evidence: `arch_report/by_target/lb_ui/xenon.txt`, `lb_ui/tui/system/components/picker.py:418`, `lb_ui/tui/system/components/picker.py:242`.
- `PhoronixTestSuite` `_run_command` (rank D) and `_load_manifest` (rank E) should move parsing and IO into dedicated helpers; evidence: `arch_report/by_target/lb_plugins/xenon.txt`, `lb_plugins/plugins/phoronix_test_suite/plugin.py:258`, `lb_plugins/plugins/phoronix_test_suite/plugin.py:549`.
- `HPL._parse_output` and `Geekbench._prepare_geekbench` (rank C/D) should move parsing/prepare into strategy objects; evidence: `arch_report/by_target/lb_plugins/xenon.txt`, `lb_plugins/plugins/hpl/plugin.py:271`, `lb_plugins/plugins/geekbench/plugin.py:221`.

### 3.5 Dead Code
- Unused import `aggregate_psutil` in psutil collector; cleanup by removing or wiring into summaries; evidence: `arch_report/by_target/lb_runner/vulture.txt`, `lb_runner/metric_collectors/psutil_collector.py:13`.

### 3.6 Dependency Hygiene
- Missing `controller_stop_runner` for molecule scenario scripts/tests; decide whether to vendor or add to dev extras; evidence: `arch_report/by_target/lb_runner/deptry.txt`, `molecule/controller-stop/scripts/test_controller_stop.py:3`, `molecule/controller-stop/tests/test_controller_stop.py:13`.
- Unused optional/dev/docs dependencies (e.g., InquirerPy, influxdb-client, pytest-cov, vulture, molecule, mkdocs) indicate drift; prune or add usage; evidence: `arch_report/by_target/lb_runner/deptry.txt`, `pyproject.toml:24`, `pyproject.toml:33`, `pyproject.toml:41`, `pyproject.toml:49`.
- Deptry flags pytest imports in tests as dev-only; decide if tests should be excluded from deptry or treated as a separate dependency scope; evidence: `arch_report/by_target/lb_runner/deptry.txt`, `molecule/controller-stop/tests/test_controller_stop.py:6`.

## Proposed Target Architecture
- Adopt a layered/ports-and-adapters structure: `lb_ui` -> `lb_app` -> domain orchestration (`lb_controller`, `lb_runner`) -> adapters (Ansible, subprocess, filesystem) with plugins/collectors as extension ports; aligns with the documented package layout; evidence: `README.md:108`, `lb_controller/engine/controller.py:72`, `lb_runner/engine/runner.py:59`.
- Dependency rules: UI depends only on `lb_app.api`, app depends on stable controller/runner/plugin APIs, domain depends on interfaces (not UI), adapters depend inward only; evidence for current API facades: `lb_app/api.py:1`, `lb_controller/api.py:1`, `lb_runner/api.py:1`.
- Public surfaces: maintain `lb_app.api`, `lb_controller.api`, `lb_runner.api`, `lb_plugins.interface.WorkloadPlugin`, and entry points for plugins/collectors; evidence: `lb_plugins/interface.py:18`, `pyproject.toml:75`, `pyproject.toml:79`.

## Staged Refactoring Roadmap

### Stage 0: Safety Net
- Goal: restore baseline test coverage by fixing the failing CLI run test; Steps: align `tests/test_cli.py` workload enabling with CLI behavior in `lb_ui/cli/commands/run.py`; Risk: Low; Validation: `pytest -m unit_ui`; Payoff: reliable regression guard; evidence: `tests/test_cli.py:551`, `lb_ui/cli/commands/run.py:158`.
- Goal: add characterization tests for controller/runner orchestration; Steps: create fake executor for `BenchmarkController` and fake generator/collector for `LocalRunner`; Risk: Low; Validation: targeted unit tests in `tests/unit_controller` and `tests/unit_runner`; Payoff: refactor safety net; evidence: `lb_controller/engine/controller.py:72`, `lb_runner/engine/runner.py:59`.
- Goal: lock down system-info output shape; Steps: snapshot `SystemInfo.to_dict/to_csv_rows` outputs in tests; Risk: Low; Validation: unit tests for `lb_runner/services/system_info.py`; Payoff: stable analytics inputs; evidence: `lb_runner/services/system_info.py:129`, `lb_runner/services/system_info.py:148`.

### Stage 1: Low-Risk Structural Refactors
- Goal: split `LocalRunner` orchestration from IO and metrics; Steps: move `_prepare_workload_dirs`, collector lifecycle, and persistence into new helpers under `lb_runner/engine` and `lb_runner/services`; Risk: Medium; Validation: runner unit tests + CLI smoke; Payoff: clearer boundaries and testability; evidence: `lb_runner/engine/runner.py:136`, `lb_runner/engine/runner.py:189`.
- Goal: separate inventory/env management from playbook execution; Steps: extract `InventoryWriter` and `EnvBuilder` from `AnsibleRunnerExecutor`, keep `RemoteExecutor` API stable; Risk: Medium; Validation: controller unit tests + minimal Ansible dry run; Payoff: smaller adapter surface; evidence: `lb_controller/adapters/ansible_runner.py:70`, `lb_controller/adapters/ansible_runner.py:165`.
- Goal: split plugin discovery vs instantiation vs installation; Steps: move entrypoint/user-dir discovery into `lb_plugins/discovery.py`, keep `PluginRegistry` as storage/factory, move packaging to `lb_plugins/installer.py`; Risk: Medium; Validation: plugin list tests and registry unit tests; Payoff: reduced multi-concern pressure; evidence: `lb_plugins/registry.py:56`, `lb_plugins/api.py:126`.
- Goal: isolate system-info collectors from data model; Steps: move `_collect_*` and `collect_system_info` into a collectors module, keep dataclasses in a types module; Risk: Low; Validation: system-info unit tests; Payoff: lower complexity and clearer API; evidence: `lb_runner/services/system_info.py:186`, `lb_runner/services/system_info.py:446`.

### Stage 2: Consolidation Refactors
- Goal: collapse plugin metadata duplication via a `SimpleWorkloadPlugin` base; Steps: introduce a base with class attributes for `name/description/paths`, update plugins to inherit; Risk: High (behavior drift across plugins); Validation: plugin registry tests + CLI `lb plugin list` + at least one end-to-end plugin run; Payoff: lower duplication and faster plugin additions; evidence: `arch_report/duplication_candidates_lb_plugins.txt`, `lb_plugins/plugins/stress_ng/plugin.py:90`, `lb_plugins/plugins/dd/plugin.py:168`.
- Goal: unify command-based generators with a template method + parser strategy; Steps: create `CommandSpec` + `ResultParser` abstractions, update StressNG/DD/Sysbench/UnixBench/Yabs/Geekbench to use them; Risk: High; Validation: generator unit tests + sample workload runs; Payoff: reduced generator duplication and clearer IO boundaries; evidence: `arch_report/duplication_candidates_lb_plugins.txt`, `lb_plugins/plugins/stress_ng/plugin.py:32`, `lb_plugins/plugins/dd/plugin.py:34`, `lb_plugins/plugins/sysbench/plugin.py:45`, `lb_plugins/plugins/unixbench/plugin.py:35`.
- Goal: consolidate presenter/dashboard implementations with shared adapters; Steps: create `PresenterBase` and `DashboardAdapter`, rewrite headless and threaded versions to delegate; Risk: Medium; Validation: unit_ui tests and headless mode checks; Payoff: less UI duplication and easier TUI evolution; evidence: `arch_report/duplication_candidates_lb_ui.txt`, `lb_ui/tui/system/headless.py:99`, `lb_ui/tui/adapters/tui_adapter.py:80`.

## Do Not Do Yet
- Do not replace Ansible orchestration or its playbook contract until controller/runner boundaries are stable; evidence: `lb_controller/engine/controller.py:21`, `lb_controller/adapters/playbooks.py:293`.
- Do not change output directory layout or journal schema until analytics/UI have characterization tests; evidence: `lb_controller/services/journal.py:161`, `lb_ui/presenters/journal.py:46`.
- Do not rewrite the CLI/TUI framework (Typer/Rich/Prompt Toolkit) before reducing picker/selection complexity; evidence: `lb_ui/cli/main.py:13`, `lb_ui/tui/system/components/picker.py:242`.
- Do not remove `lb_app.api` facade until dependency rules are enforced; evidence: `lb_app/api.py:1`.
