# GUI Implementation Plan (Detailed)

## 0. Summary
Build a **native cross‑platform GUI** (PySide6) that exposes the same app capabilities as the CLI/TUI, but via a clean, GUI‑oriented architecture. The GUI must consume only **`lb_app.api`** (and `lb_common.api`) and must not import `lb_ui`, `lb_controller`, or `lb_runner` directly.

This plan is written so another agent can implement the GUI end‑to‑end.

---

## 1. Hard Constraints
- **Dependencies:** GUI may import **only `lb_app.api` and `lb_common.api`** (plus standard libs / PySide6 / Matplotlib).
- **Execution modes:** **remote**, **docker**, **multipass**. Local execution is not supported.
- **Logging:** entrypoint must call `lb_common.configure_logging()`.
- **No back‑compat**: we can change GUI design freely for maintainability.

---

## 2. Package Layout
Create a new package `lb_gui/` parallel to `lb_ui/`.

```
lb_gui/
  __init__.py
  main.py                    # console entrypoint (lb gui)
  app.py                     # QApplication setup and global services
  resources/                 # icons, style sheets
  windows/
    main_window.py
  views/
    run_setup_view.py
    dashboard_view.py
    results_view.py
    analytics_view.py
    config_view.py
    plugins_view.py
    doctor_view.py
  viewmodels/
    run_setup_vm.py
    dashboard_vm.py
    results_vm.py
    analytics_vm.py
    config_vm.py
    plugins_vm.py
    doctor_vm.py
  services/
    app_client.py            # thin wrapper around lb_app.api.ApplicationClient
    run_controller.py        # run lifecycle + UIHooks -> Qt signals
    run_catalog.py           # RunCatalogService wrapper
    config_service.py        # ConfigService wrapper
    plugin_service.py        # plugin list/enable/disable/select + cache invalidation
    analytics_service.py     # AnalyticsService wrapper
    doctor_service.py        # DoctorService wrapper
    provision_service.py     # (optional) ProvisionService wrapper for docker/multipass
  workers/
    run_worker.py            # QThread/QObject: start_run, forward hooks
    analytics_worker.py      # QThread for analytics
    doctor_worker.py         # QThread for doctor checks
  widgets/
    plan_table.py            # plan grid widget
    journal_table.py         # journal grid widget
    log_viewer.py            # streaming log viewer
    status_bar.py            # run status summary
    file_picker.py
  utils/
    qt.py                    # common Qt helpers
    formatters.py            # common formatting (durations etc.)
```

---

## 3. API Usage Map (lb_app.api)
Use only these stable APIs:

- **Run orchestration**
  - `ApplicationClient` (alias: `AppClient`)
  - `RunRequest`, `RunContext`, `RunResult`
  - `RunJournal`, `RunStatus`, `RunEvent`, `TaskState`
  - `RunCatalogService`, `RunExecutionSummary`
  - `UIHooks` — Protocol with 5 callbacks (see Section 6)
  - `MAX_NODES`

- **UI protocols & adapters**
  - `UIAdapter` — Protocol for full UI integration
  - `DashboardHandle`, `ProgressHandle` — Protocols for live updates
  - `NoOpUIAdapter`, `NoOpDashboardHandle`, `NoOpProgressHandle` — No-op implementations

- **Config & plugins**
  - `ConfigService`, `BenchmarkConfig`, `WorkloadConfig`, `RemoteHostConfig`
  - `PluginRegistry`, `build_plugin_table`, `create_registry`, `reset_registry_cache`
  - `WorkloadIntensity`

- **Doctor**
  - `DoctorService`, `DoctorReport`, `DoctorCheckGroup`, `DoctorCheckItem`

- **Analytics**
  - `AnalyticsService`, `AnalyticsRequest`, `AnalyticsKind`

- **Provisioning**
  - `ProvisionService`, `ProvisionConfigSummary`, `ProvisionStatus`

- **Viewmodels (UI‑agnostic)**
  - `build_dashboard_viewmodel`, `DashboardViewModel`, `DashboardSnapshot`
  - `DashboardRow`, `DashboardStatusSummary`, `DashboardLogMetadata`
  - `journal_rows`, `plan_rows`, `summarize_progress`, `target_repetitions`
  - `event_status_line`

- **Utilities**
  - `summarize_system_info`, `results_exist_for_run`
  - `RemoteHostSpec`, `RunInfo`

- **Common (lb_common.api)**
  - `configure_logging` — Must be called in entrypoint

---

## 4. Core Architecture
### 4.1 App bootstrap
- `lb_gui/main.py` calls `lb_common.configure_logging()` and starts `QApplication`.
- `lb_gui/app.py` builds shared services and the `MainWindow`.

### 4.2 Service Layer (GUI‑agnostic, testable)
Each service wraps an `lb_app.api` class and exposes synchronous methods. Long work is done in `workers/`.

- `services/app_client.py`
  - Holds a single `ApplicationClient` instance.
- `services/run_controller.py`
  - Builds `RunRequest`.
  - Provides `start_run_async()` that spawns `RunWorker`.
- `services/config_service.py`
  - Wrap `ConfigService` for load/save/default path.
- `services/plugin_service.py`
  - Uses `create_registry()` and platform config toggles.
  - **Important:** Call `reset_registry_cache()` or `create_registry(refresh=True)` after installing new plugins at runtime. (Enabling/disabling plugins modifies platform config, not the registry cache.)
- `services/run_catalog.py`
  - Wrap `RunCatalogService`.
- `services/analytics_service.py`
  - Wrap `AnalyticsService`.
- `services/doctor_service.py`
  - Wrap `DoctorService`.
- `services/provision_service.py` *(optional)*
  - Wrap `ProvisionService` for docker/multipass lifecycle if exposing provisioning controls beyond what `ApplicationClient` handles automatically.

### 4.3 RunRequest Dataclass
The `RunRequest` dataclass (from `lb_app.api`) defines all run parameters:

```python
@dataclass
class RunRequest:
    config: BenchmarkConfig
    tests: Sequence[str]           # workload names to run
    run_id: str | None = None
    resume: str | None = None
    debug: bool = False
    intensity: str | None = None   # low/medium/high/user_defined
    setup: bool = True
    stop_file: Path | None = None
    execution_mode: str = "remote" # remote, docker, multipass
    repetitions: int | None = None
    node_count: int = 1            # for docker/multipass only
    docker_engine: str = "docker"
    ui_adapter: UIAdapter | None = None
    skip_connectivity_check: bool = False
    connectivity_timeout: int = 10
```

### 4.4 Workers (threading)
- **RunWorker** (QThread):
  - Inputs: `RunRequest`, hooks sink.
  - Implements `UIHooks` to emit Qt signals for logs, warnings, status, events, journal updates.
- **AnalyticsWorker**: runs analytics with `AnalyticsService.run()`.
- **DoctorWorker**: executes checks to keep UI responsive.

### 4.5 ViewModels (UI‑level state)
ViewModels own state and expose Qt signals to views. They should be thin wrappers around the services.

**Important:** `lb_app.api` already exports `DashboardViewModel`, `DashboardSnapshot`, and related types. The GUI viewmodels should **wrap** these, not duplicate them.

Key VMs:
- `RunSetupViewModel`
  - Holds selected workloads, intensity, repetitions, execution mode.
  - Validates node count against `MAX_NODES`.
- `DashboardViewModel` (Qt wrapper)
  - Wraps `lb_app.api.DashboardViewModel` and `build_dashboard_viewmodel()`.
  - Exposes Qt signals for snapshot updates.
  - Uses `DashboardSnapshot`, `DashboardRow`, `DashboardStatusSummary` from API.
- `ResultsViewModel`
  - Uses `RunCatalogService` to list runs.
- `AnalyticsViewModel`
  - Builds `AnalyticsRequest` and triggers worker.
- `ConfigViewModel`
  - Load/save config, set default.
- `PluginsViewModel`
  - Enable/disable and list plugins.
  - Uses `build_plugin_table()` for display data.
- `DoctorViewModel`
  - Runs doctor checks and stores report.
  - Uses `DoctorReport`, `DoctorCheckGroup`, `DoctorCheckItem` from API.

---

## 5. GUI Views (Qt Widgets)
### 5.1 MainWindow
- Layout: sidebar navigation + stacked views.
- Sections: Run Setup, Dashboard, Results, Analytics, Config, Plugins, Doctor.

### 5.2 Run Setup View
- Workload selection list (from registry).
- Intensity dropdown (low/medium/high/user_defined).
- Repetitions, run id, stop file.
- Execution mode selectors (remote/docker/multipass).
- Node count input (enabled when docker/multipass).
- Start button -> triggers run worker.

### 5.3 Dashboard View
- Run plan table (from `plan_rows`).
- Journal table (from `journal_rows` or dashboard snapshot).
- Status bar with summary counts (completed/running/failed).
- Log viewer with streaming lines.

### 5.4 Results View
- List past runs (from `RunCatalogService`).
- Show run details (journal path, host list, workloads).
- Open artifacts paths (CSV/report/export).

### 5.5 Analytics View
- Select run + workloads + hosts.
- Run analytics -> display generated artifacts + chart preview.

### 5.6 Config View
- Load config (default path or user selected).
- Edit key fields (hosts, repetitions, output dirs).
- Save and set default.

### 5.7 Plugins View
- List plugins (enabled/disabled).
- Toggle enabled state in platform config.

### 5.8 Doctor View
- Run checks and show groups + status.

---

## 6. Threading & Signal Contract

### 6.1 UIHooks Protocol (lb_app.api)
The `UIHooks` protocol defines 5 callbacks that `ApplicationClient.start_run()` invokes:

```python
class UIHooks(Protocol):
    def on_log(self, line: str) -> None: ...
    def on_status(self, controller_state: str) -> None: ...
    def on_warning(self, message: str, ttl: float = 10.0) -> None: ...
    def on_event(self, event: RunEvent) -> None: ...
    def on_journal(self, journal: RunJournal) -> None: ...
```

### 6.2 Qt Signals for RunWorker
Define these signals to bridge UIHooks to Qt's main thread:

| Qt Signal | UIHooks Method | Notes |
|-----------|----------------|-------|
| `log_line(str)` | `on_log` | Raw log forwarding |
| `status_line(str)` | `on_status` | Controller state changes |
| `warning(str, float)` | `on_warning` | **Include TTL** for auto-dismiss |
| `event_update(object)` | `on_event` | RunEvent object |
| `journal_update(object)` | `on_journal` | RunJournal object |
| `finished(bool, str)` | — | Emitted when `start_run()` returns |

**Notes:**
- `finished` has no UIHooks equivalent — emit it when the blocking `start_run()` call completes.
- `warning` must include the TTL parameter (default 10.0 seconds) for transient warning display.
- All signal handlers must be connected with `Qt.QueuedConnection` to ensure UI updates run on the main thread.

### 6.3 UIAdapter Alternative
For richer integration, implement the `UIAdapter` protocol instead of (or in addition to) UIHooks:
- Provides `create_dashboard()` returning a `DashboardHandle`
- Provides `create_progress()` returning a `ProgressHandle`
- Set `RunRequest.ui_adapter` to use it

**Rule:** All UI updates are executed on the main thread.

---

## 7. Error Handling
- Convert exceptions into UI messages with a clear title and detail.
- If `ApplicationClient.start_run()` returns `None`, surface a warning and keep the UI idle.
- Always stop worker threads gracefully on cancellation.

---

## 8. Tests to Create
### 8.1 Unit tests (pure python)
- `tests/unit/lb_gui/test_run_controller.py`
  - Build `RunRequest` with different modes; validates node count bounds.
- `tests/unit/lb_gui/test_plugin_service.py`
  - Enable/disable plugins updates platform config.
- `tests/unit/lb_gui/test_results_vm.py`
  - Run catalog listing and selection.

### 8.2 Worker tests (no Qt UI)
- `tests/unit/lb_gui/test_run_worker.py`
  - Use a fake `ApplicationClient` that returns a stub `RunResult`.
  - Ensure signals fire for log/status/journal.

### 8.3 Qt tests (optional, if adding pytest‑qt)
- `tests/qt/test_run_setup_view.py`
  - Fill form, press Run, verify calls to RunController.

**Dependencies for Qt tests:** add `pytest-qt` to dev extras if desired.

---

## 9. Implementation Phases
1. **Phase A:** Bootstrap app, MainWindow, service layer. ✅ **COMPLETED**
   - Created `lb_gui/` package structure
   - Implemented service layer wrappers (app_client, config, plugin, run_catalog, analytics, doctor)
   - Created MainWindow with sidebar navigation and placeholder views
   - Added PySide6 dependency and `lb-gui` entrypoint to pyproject.toml
   - Added unit tests for all services (15 tests passing)
2. **Phase B:** Run Setup + RunWorker + Dashboard view (core). ✅ **COMPLETED**
   - Created `RunWorker` with `UIHooksAdapter` bridging UIHooks to Qt signals
   - Created `RunSetupViewModel` with workload selection, validation, and RunRequest building
   - Created `RunSetupView` with workload list, parameters form, and start button
   - Created `GUIDashboardViewModel` wrapping `lb_app.api.DashboardViewModel`
   - Created `DashboardView` with plan table, journal table, status summary, and log viewer
   - Added unit tests (31 new tests, 46 total passing)
3. **Phase C:** Results + Analytics. ✅ **COMPLETED**
   - Created `ResultsViewModel` for listing and selecting past runs
   - Created `ResultsView` with run table, details panel, and directory open buttons
   - Created `AnalyticsViewModel` for configuring and running analytics
   - Created `AnalyticsView` with run selection, filters, and artifact display
   - Added unit tests (23 new tests, 69 total passing)
4. **Phase D:** Config + Plugins + Doctor. ✅ **COMPLETED**
   - Created `ConfigViewModel` and `ConfigView` for loading/viewing configuration
   - Created `PluginsViewModel` and `PluginsView` for enabling/disabling plugins
   - Created `DoctorViewModel` and `DoctorView` for environment health checks
   - Added unit tests (17 new tests, 86 total passing)
5. **Phase E:** Packaging + `lb gui` CLI entrypoint. ✅ **COMPLETED**
   - Wired MainWindow with all real ViewModels and Views (run_setup, dashboard, results, analytics, config, plugins, doctor)
   - Connected run setup → dashboard flow via RunWorker for live benchmark execution
   - Verified GUI imports and startup work correctly
   - All 86 unit tests passing

---

## 10. Acceptance Criteria
- GUI can run remote benchmark end‑to‑end without freezing.
- Dashboard updates live (logs + journal status).
- Results and analytics are visible.
- Config and plugins are editable through GUI.
- GUI never imports `lb_ui`, `lb_controller`, or `lb_runner`.
