# Issue: Decouple Dashboard Rendering from App Models

**Title:** Refactor: Introduce a Dashboard viewmodel and remove direct `lb_app.api` imports

**Priority:** Medium
**Component:** lb_ui

**Description:**
`lb_ui/tui/system/components/dashboard.py` and `dashboard_helpers.py` import `lb_app.api` types directly and compute presentation data on the fly. This couples UI rendering to domain objects and makes it harder to evolve the app layer. Introduce a `DashboardViewModel` (and supporting DTOs) so the dashboard consumes only view data.

**Detailed Plan:**
1. Define a new viewmodel in `lb_ui/presenters/dashboard.py` (or `run_viewmodels.py`):
   - `DashboardViewModel` containing plan rows, journal rows, status summary, intensity map, log metadata, and run id.
   - `DashboardRow` or a simple list-of-lists structure with explicit fields for host/workload/status/progress.
2. Move dashboard data shaping into the presenter:
   - Intensity mapping
   - Status/progress computation
   - Latest duration formatting
   - Event status string
3. Update `DashboardFactory.create(...)` to accept the viewmodel instead of `RunJournal`.
4. Update `TUIAdapter.create_dashboard` and any controller/app call sites to build the viewmodel before calling the TUI.
5. Update headless implementations to accept and record viewmodels.
6. Remove `lb_app.api` imports from TUI components and helpers.
7. Add a small unit test ensuring viewmodel construction yields expected rows/status text.

**Acceptance Criteria:**
- TUI dashboard code (`dashboard.py`, `dashboard_helpers.py`) no longer imports `lb_app.api`.
- Dashboard rendering depends only on viewmodels/DTOs.
- The UI still renders the same information for a given run.
- At least one test validates viewmodel construction.

## Notes
- 2026-01-23: Added `lb_ui/presenters/dashboard.py` with `DashboardViewModel`, snapshot DTOs, and event/status helpers.
- 2026-01-23: Refactored TUI dashboard + headless dashboard factory to consume viewmodels; removed app-model imports from TUI components.
- 2026-01-23: Updated session manager + UI adapters to build and pass viewmodels; added unit coverage for dashboard viewmodel.
- 2026-01-23: Restored dependency direction (lb_app no longer imports lb_ui); viewmodel creation lives in lb_ui adapter.

## Testing
- 2026-01-23: `uv run pytest tests/unit/lb_ui/test_adapters_dashboard.py tests/unit/lb_ui/test_dashboard_viewmodel.py tests/unit/lb_app/test_ui_interfaces.py`
- 2026-01-23: `uv run pytest tests/unit/lb_ui/test_adapters_dashboard.py tests/unit/lb_app/test_ui_interfaces.py tests/unit/lb_ui/test_run_viewmodels.py tests/unit/lb_ui/test_dashboard_viewmodel.py`
