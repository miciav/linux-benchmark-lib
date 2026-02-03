# Issue: Simplify Dashboard Adapter Layering

**Title:** Refactor: Simplify dashboard threading and adapter layers

**Priority:** Medium
**Component:** lb_ui

**Description:**
Dashboard rendering uses multiple adapter layers (`DashboardAdapter`, `ThreadedDashboardHandle`) with subtly different refresh behavior. This increases complexity and risks inconsistent refresh semantics. Simplify to a single adapter that owns threading and refresh behavior.

**Detailed Plan:**
1. Define a single `DashboardHandle` implementation in `lb_ui/tui/adapters/dashboard_handle.py` that:
   - Wraps a `Dashboard` implementation
   - Optionally runs in a background thread
   - Ensures refresh behavior is consistent and explicit
2. Update `TUIAdapter.create_dashboard` to return this new handle.
3. Deprecate or remove `ThreadedDashboardHandle` and reduce usage of `DashboardAdapter` if no longer needed.
4. Ensure headless dashboard implementations still work as expected.
5. Add a small test that simulates `add_log` and `refresh` calls in threaded and non-threaded modes.

**Acceptance Criteria:**
- Only one adapter/handle layer exists for dashboard usage.
- Refresh semantics are consistent across threaded and non-threaded paths.
- Headless dashboards remain functional.

## Notes
- 2026-01-23: Added `lb_ui/tui/adapters/dashboard_handle.py` as the single handle/adapter.
- 2026-01-23: Updated TUI adapter and headless dashboard factory to use the new handle and removed the old adapter layer.
- 2026-01-23: Removed `ThreadedDashboardHandle` export and simplified tests to target the new handle.

## Testing
- 2026-01-23: `uv run pytest tests/unit/lb_ui/test_adapters_dashboard.py`
