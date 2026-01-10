# Architecture Review 2026: Linux Benchmark Library

## 1. Executive Summary
*   **High-Level Status**: The system follows a layered architecture (`lb_ui` -> `lb_app` -> `lb_runner`/`lb_controller`), but `lb_app` has evolved into a "God Layer" containing monolithic service classes.
*   **Critical Findings**:
    1.  **Monolithic Services**: `lb_app.services.RunService` (36 methods) and `lb_app.services.ConfigService` (19 methods) violate SRP, mixing orchestration, state management, and I/O.
    2.  **Import Cycle**: A circular dependency exists in `lb_app` between `run_service` and `remote_run_coordinator`.
    3.  **Duplication**: `lb_controller` contains duplicate process management logic in `ansible_helpers.py` (84% similarity).
    4.  **Local Runner Complexity**: `LocalRunner` in `lb_runner` is a large class (22 methods) handling too many execution aspects.
*   **Risk Assessment**: Moderate. The cycle in `lb_app` makes refactoring harder, and the large services inhibit testing isolation.
*   **Recommendation**: Break `RunService` into distinct use-case handlers (e.g., `LocalRunExecutor`, `RemoteRunExecutor`) and extract a common `ProcessManager` in `lb_controller`.

## 2. Current Architecture Map

**Package Roles**:
*   **`lb_ui`**: Presentation layer (CLI/TUI). Imports `lb_app.api`.
*   **`lb_app`**: Service/Facade layer. Orchestrates logic. **(Problem Area: Heavy accumulation of logic)**.
*   **`lb_runner`**: Core domain execution. Runs benchmarks locally.
*   **`lb_controller`**: Remote orchestration. Uses Ansible.
*   **`lb_plugins`**: Workload implementations (Stress-ng, FIO, etc.).
*   **`lb_common`**: Shared utilities.

**Core Flow**:
`CLI (lb_ui)` -> `Service (lb_app)` -> `Controller (lb_controller)` -> `Runner (lb_runner)` -> `Plugins`

## 3. Evidence-Driven Findings

### 3.1 Cycles & Dependency Issues
**Found 1 Cycle in `lb_app`:**
*   `lb_app.services.remote_run_coordinator` -> `lb_app.services.run_service` -> `lb_app.services.remote_run_coordinator`
    *   *Impact*: Tightly couples remote coordination with generic run logic, making it hard to split local vs remote execution.

### 3.2 Duplication Candidates
| Similarity | Source A | Source B | Recommendation |
| :--- | :--- | :--- | :--- |
| **0.84** | `ProcessStopController` (lb_controller) | `PlaybookProcessRunner` (lb_controller) | **Extract Base Class**: `AnsibleProcessHandler`. Both share lifecycle methods (`interrupt`, `is_running`). |

### 3.3 Multi-Concern Hotspots (God Objects)
| Class | Methods | Responsibilities | Proposed Decomposition |
| :--- | :--- | :--- | :--- |
| **`RunService`** (`lb_app`) | 36 | Config loading, local run, remote run, output formatting, error handling. | Split into `RunOrchestrator` (facade) and specialized executors: `LocalExecutor`, `RemoteExecutor`. |
| **`ConfigService`** (`lb_app`) | 19 | File I/O, validation, default injection, migration. | Extract `ConfigLoader` (I/O) and `ConfigValidator` (Logic). |
| **`LocalRunner`** (`lb_runner`) | 22 | Plugin loading, execution loop, metric collection, signal handling. | Extract `PluginLoader` and `MetricCollectorManager` to collaborators. |
| **`AnsibleOutputFormatter`** (`lb_app`) | 23 | Parsing Ansible JSON, formatting TUI output, logging. | Move parsing logic to `lb_controller` (domain) and keep only formatting in `lb_app` or `lb_ui`. |

### 3.4 Complexity Hotspots
*   `lb_runner/models/config.py`: `ansible_host_line` (CCN 5). Manageable, but indicates config logic is leaking into models.
*   `lb_app` services generally have high coupling (fan-out) due to importing many other parts of the system.

### 3.5 Dependency Hygiene
*   `urllib3` declared but unused in `lb_runner`. Likely transitive.
*   `lb_ui` correctly isolates itself from `lb_controller` internals, using `lb_app` as a gateway.

## 4. Target Architecture Proposal

**Pattern**: Hexagonal / Ports & Adapters (Lightweight)

*   **Domain Core**: `lb_runner` (Execution Model), `lb_controller` (Orchestration Model).
*   **Application Services**: `lb_app` (Use Cases). *Must be thin.*
*   **Adapters**:
    *   *Driving*: `lb_ui` (CLI/TUI).
    *   *Driven*: `lb_plugins` (Workloads), `Ansible` (Infrastructure).

**Rules**:
1.  `lb_app` should *coordinate*, not *implement* heavy logic.
2.  `lb_ui` must never import `lb_runner` or `lb_controller` directly.
3.  `lb_runner` and `lb_controller` should be independent of `lb_app`.

## 5. Refactoring Roadmap

### Stage 0: Safety Net (High Priority)
*   **Goal**: Ensure refactoring doesn't break existing runs.
*   **Actions**:
    1.  Add characterization tests for `RunService.run_benchmark` (mocking the runner/controller).
    2.  Snapshot `lb_config` parsing output to prevent regression during `ConfigService` refactor.

### Stage 1: Low-Risk Structural Refactors
*   **Goal**: Clean up obvious debt and break cycles.
*   **Actions**:
    1.  **Break Cycle**: Extract interface `IRunCoordinator` that `RunService` depends on, and implement it in `RemoteRunCoordinator`. Or move shared types to `lb_app.services.types`.
    2.  **Deduplicate Controller**: Create `AnsibleProcessHandler` base class in `lb_controller/adapters/ansible_helpers.py`.
    3.  **Cleanup**: Remove unused `urllib3` dependency in `lb_runner`.

### Stage 2: Consolidation & Decomposition
*   **Goal**: Decompose God Objects.
*   **Actions**:
    1.  **Split `RunService`**:
        *   Move `local_execution` logic to `lb_app.execution.local`.
        *   Move `remote_execution` logic to `lb_app.execution.remote`.
        *   Keep `RunService` as a thin facade.
    2.  **Refactor `LocalRunner`**: Extract `MetricManager` from `LocalRunner` to handle collector lifecycles.

## 6. "Do NOT do yet"
*   **Full AsyncIO Rewrite**: The current blocking/threaded model works. rewriting to async would be high risk/low reward right now.
*   **Plugin System Overhaul**: `lb_plugins` seems stable. Don't touch unless adding a new plugin type requires it.
*   **Merging `lb_runner` and `lb_controller`**: Keep them separate. Local vs Remote concerns are distinct enough.
