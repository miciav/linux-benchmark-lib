# Architecture Review Report
**Date**: 2026-01-02
**Packages Analyzed**: lb_plugins, lb_ui, lb_controller, lb_runner

---

## 1. Executive Summary (Ranked by Impact)

1. **CRITICAL: Import cycle in dfaas plugin** - `generator -> plugin -> generator` cycle breaks modularity
2. **HIGH: Massive plugin duplication** - 30+ plugin pairs with 80-100% method similarity (sim=1.0 for 5 pairs)
3. **HIGH: Legacy code in dfaas** - `legacy_materials/` contains 4 Python files with rank E complexity
4. **HIGH: BenchmarkController is a God object** - 23 methods, 8 init params, orchestrator+logic mixed
5. **HIGH: All generators mix IO + logic** - 16 hotspots flagged `io_plus_logic_mixed`
6. **MEDIUM: 79 unused imports** - Ruff found 161 linting errors, 85 auto-fixable
7. **MEDIUM: Complexity hotspots** - PhoronixGenerator `_load_manifest` rank E, `_run_command` rank D
8. **MEDIUM: AnsibleRunnerExecutor** - 18 methods mixing IO + logic
9. **LOW: Security issues** - `tarfile.extractall` without validation (High severity)
10. **LOW: Transitive dependency issue** - `requests` used in legacy code but not declared

---

## 2. Current Architecture Map

```
┌─────────────────────────────────────────────────────────────┐
│                        lb_ui (41 files)                      │
│   CLI entry point → lb_ui.cli.main:main                     │
│   Responsibilities: CLI commands, TUI rendering, user input │
└─────────────────────────────┬───────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────┐
│                   lb_controller (33 files)                   │
│   Responsibilities: Orchestration, Ansible execution,       │
│   state machine, remote execution coordination               │
│   Key classes: BenchmarkController, AnsibleRunnerExecutor   │
└─────────────────────────────┬───────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────┐
│                     lb_runner (33 files)                     │
│   Responsibilities: Workload execution, metric collection,  │
│   local runner daemon, config models                         │
│   Entry points: collectors (psutil, cli)                     │
└─────────────────────────────┬───────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────┐
│                    lb_plugins (48 files)                     │
│   Responsibilities: Workload plugins, generators, registry  │
│   Plugins: stress_ng, fio, dd, hpl, stream, unixbench,      │
│           sysbench, yabs, geekbench, phoronix, dfaas        │
└─────────────────────────────────────────────────────────────┘

Supporting packages:
- lb_common (6 files): Shared utilities, logging
- lb_analytics (11 files): Data analysis, reporting
- lb_provisioner (12 files): Infrastructure provisioning
- lb_app (20 files): Application-level abstractions
```

---

## 3. Evidence Tables

### 3.1 Import Cycles

| Cycle | Location | Impact |
|-------|----------|--------|
| `generator -> plugin -> generator` | `lb_plugins/plugins/dfaas/` | **CRITICAL** - Breaks isolation between generator and plugin |

**Evidence** (`arch_report/grimp_cycles.txt`):
```
lb_plugins.plugins.dfaas.generator -> lb_plugins.plugins.dfaas.plugin -> lb_plugins.plugins.dfaas.generator
```

**Recommended Fix**: Extract shared types/interfaces to a separate module (e.g., `dfaas/types.py`).

---

### 3.2 Duplication Candidates (Top Priority)

| Similarity | Class A | Class B | Recommendation |
|------------|---------|---------|----------------|
| **1.00** | StressNGPlugin | DDPlugin | **MERGE** → use SimpleWorkloadPlugin |
| **1.00** | FIOPlugin | StreamPlugin | **MERGE** → use SimpleWorkloadPlugin |
| **1.00** | FIOPlugin | HPLPlugin | **MERGE** → use SimpleWorkloadPlugin |
| **1.00** | StreamPlugin | HPLPlugin | **MERGE** → use SimpleWorkloadPlugin |
| **1.00** | YabsPlugin | GeekbenchPlugin | **MERGE** → use SimpleWorkloadPlugin |
| 0.91 | HPLPlugin | GeekbenchPlugin | Extract common export_results_to_csv |
| 0.89 | UnixBenchGenerator | SysbenchGenerator | Extract CommandGenerator base |
| 0.82 | StressNGGenerator | DDGenerator | Extract CommandGenerator base |

**Evidence** (`arch_report/duplication_candidates_lb_plugins.txt`):
- 30+ plugin pairs with >80% method similarity
- Common methods: `config_cls`, `create_generator`, `description`, `get_ansible_setup_path`, etc.

**Recommended Action**:
1. Existing `SimpleWorkloadPlugin` should be used more aggressively
2. Create a `CommandGeneratorMixin` for shared subprocess logic
3. Factor out `export_results_to_csv` into a utility function

---

### 3.3 Multi-Concern / God Objects (Hotspots)

| Class | Methods | Init Params | Flags | Decomposition Proposal |
|-------|---------|-------------|-------|------------------------|
| `BenchmarkController` | 23 | 8 | orchestrator, many_methods, init_too_many_params | Split into: RunOrchestrator, SetupCoordinator, StateManager |
| `AnsibleRunnerExecutor` | 18 | 5 | many_methods, io_plus_logic_mixed | Extract: PlaybookRunner, InventoryManager |
| `DfaasGenerator` | 21 | 3 | many_methods, io_plus_logic_mixed | Extract: K6Orchestrator, MetricsCollector, ResultAggregator |
| `StreamGenerator` | 16 | 2 | many_methods, io_plus_logic_mixed | Use CommandGenerator base properly |
| `HPLGenerator` | 15 | 2 | many_methods, io_plus_logic_mixed | Use CommandGenerator base properly |
| `K6Runner` | 7 | **9** | init_too_many_params, io_plus_logic_mixed | Use configuration object pattern |

**Evidence** (`arch_report/hotspots.txt`, `arch_report/hotspots_lb_controller.txt`)

---

### 3.4 Complexity Hotspots

| Location | Function/Class | Complexity | Action |
|----------|---------------|------------|--------|
| `phoronix_test_suite/plugin.py:528` | `_load_manifest` | **E** (very high) | Extract parser, use strategy pattern |
| `phoronix_test_suite/plugin.py:247` | `_run_command` | **D** | Extract error handling |
| `geekbench/plugin.py:231` | `_prepare_geekbench` | **D** | Split into smaller methods |
| `geekbench/plugin.py:393` | `export_results_to_csv` | **D** | Extract CSV writer utility |
| `installer.py:48` | `package` | **C** | Use strategy for archive types |
| `installer.py:128` | `_install_directory` | **C** | Split validation from installation |
| `dfaas/legacy_materials/.../samples-generator.py:46` | `main` | **E** | **DELETE** (legacy code) |

**Evidence** (`arch_report/xenon.txt`, `arch_report/radon_cc.txt`)

---

### 3.5 Dead Code / Legacy Code

| Location | Type | Action |
|----------|------|--------|
| `lb_plugins/plugins/dfaas/legacy_materials/` | Legacy directory | **DELETE** - 4 Python files with rank E complexity |
| `lb_plugins/plugins/dfaas/generator.py:18` | Unused import | Remove `ConfigExecutionError` |
| `lb_controller/ansible/playbooks_legacy_pip/` | Legacy playbooks | Already deleted (was in previous report) |

**Evidence** (`arch_report/vulture.txt`, `arch_report/xenon.txt`)

---

### 3.6 Dependency Hygiene

| Issue | Location | Impact |
|-------|----------|--------|
| `utils` imported but missing | `legacy_materials/samples-generator*.py` | Breaks if legacy code is run |
| `requests` transitive dependency | `legacy_materials/utils.py` | Not declared in pyproject.toml |

**Evidence** (`arch_report/deptry.txt`)

**Recommendation**: Delete `legacy_materials/` folder entirely.

---

## 4. Proposed Target Architecture

### Layered Architecture with Plugin System

```
┌─────────────────────────────────────────────────────────────┐
│                    PRESENTATION LAYER                        │
│  lb_ui/cli/, lb_ui/tui/                                     │
│  - CLI commands only, no business logic                      │
│  - Depends on: Application Layer                             │
└─────────────────────────────┬───────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────┐
│                   APPLICATION LAYER                          │
│  lb_controller/engine/, lb_runner/services/                 │
│  - Orchestration, use cases, state machine                  │
│  - Depends on: Domain Layer, Adapters (ports)               │
└─────────────────────────────┬───────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────┐
│                      DOMAIN LAYER                            │
│  lb_runner/models/, lb_plugins/interface.py                 │
│  - Business logic, plugin contracts, value objects          │
│  - NO external dependencies                                  │
└─────────────────────────────┬───────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────┐
│                    INFRASTRUCTURE LAYER                      │
│  lb_controller/adapters/, lb_plugins/plugins/               │
│  - Ansible execution, subprocess, file I/O                  │
│  - Implements interfaces from Domain Layer                   │
└─────────────────────────────────────────────────────────────┘
```

### Dependency Rules

1. **Presentation → Application**: CLI can call controller methods
2. **Application → Domain**: Controller uses domain models
3. **Application → Infrastructure (via ports)**: Controller uses adapters via interfaces
4. **Infrastructure → Domain**: Adapters implement domain interfaces
5. **NO**: Domain → Infrastructure (domain must be pure)
6. **NO**: Presentation → Infrastructure (no direct Ansible calls from CLI)

---

## 5. Staged Refactoring Roadmap

### Stage 0: Safety Net

| Task | Risk | Validation |
|------|------|------------|
| Add characterization tests for BenchmarkController | Low | Snapshot current behavior |
| Add integration tests for plugin generators | Low | Test each plugin in isolation |
| Increase unit test coverage to 60% | Low | `pytest --cov` gate |
| Document "golden paths" for remote execution | Low | Manual verification |

### Stage 1: Low-Risk Structural Refactors

| Task | Files | Risk | Validation |
|------|-------|------|------------|
| **Delete legacy_materials/** | `lb_plugins/plugins/dfaas/legacy_materials/` | **Low** | No imports found |
| Fix 85 auto-fixable Ruff errors | Multiple | **Low** | `ruff check --fix` |
| Remove unused import in dfaas/generator.py | `generator.py:18` | **Low** | Tests pass |
| Break dfaas import cycle | `dfaas/generator.py`, `dfaas/plugin.py` | **Medium** | Extract `dfaas/types.py` |
| Extract K6Runner config object | `dfaas/services/k6_runner.py` | **Medium** | Unit tests |

### Stage 2: Consolidation Refactors

| Task | Files | Risk | Validation |
|------|-------|------|------------|
| Migrate plugins to SimpleWorkloadPlugin | All `*Plugin` classes | **Medium** | Plugin tests |
| Extract CommandGeneratorMixin | All `*Generator` classes | **Medium** | Generator tests |
| Split BenchmarkController | `lb_controller/engine/controller.py` | **High** | Integration tests |
| Split AnsibleRunnerExecutor | `lb_controller/adapters/ansible_runner.py` | **High** | E2E tests |
| Extract CSV export utility | Multiple plugin files | **Low** | Unit tests |

---

## 6. "Do NOT Do Yet" List

| Tempting Refactor | Why Not Now |
|-------------------|-------------|
| Rewrite DfaasGenerator from scratch | Too many dependencies, needs comprehensive tests first |
| Migrate to hexagonal architecture | Requires Stage 0-1 completion first |
| Replace Ansible with pure Python | Major scope creep, Ansible works |
| Add type hints everywhere | Focus on structural issues first |
| Refactor PhoronixGenerator complexity | Needs characterization tests first |

---

## Appendix: Tool Outputs Summary

| Report | Key Findings |
|--------|--------------|
| `grimp_cycles.txt` | 1 import cycle (dfaas) |
| `hotspots.txt` | 16 classes flagged as hotspots |
| `duplication_candidates.txt` | 6 pairs in final analysis, 30+ in lb_plugins |
| `ruff_stats.txt` | 161 errors, 79 unused imports |
| `xenon.txt` | 24 complexity violations (C-E rank) |
| `vulture.txt` | 1 unused import |
| `deptry.txt` | 3 dependency issues (all in legacy code) |
| `bandit.txt` | 1 High severity (tarfile), multiple Low |
