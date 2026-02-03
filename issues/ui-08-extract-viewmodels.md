# Issue: Extract UI-Agnostic ViewModels to lb_app

**Title:** Refactor: Move run/dashboard viewmodels out of lb_ui

**Priority:** Medium
**Component:** lb_app

**Description:**
`lb_ui` contains logic-only viewmodel helpers for run plans and dashboard state. To allow reuse by GUI and keep `lb_ui` thin, extract these into `lb_app` and expose them via the stable `lb_app.api` surface. Keep TUI-specific formatting in `lb_ui`.

**Detailed Plan:**
1. Move `lb_ui/presenters/run_viewmodels.py` to `lb_app/viewmodels/run_viewmodels.py`.
2. Move `lb_ui/presenters/dashboard.py` logic to `lb_app/viewmodels/dashboard.py` (exclude TUI theme helpers).
3. Keep a small `lb_ui` wrapper for `event_status_line` or TUI-only helpers.
4. Update `lb_app/api.py` exports for new viewmodel types and builders.
5. Update `lb_ui` imports to use `lb_app.api` only.
6. Update unit tests to import from `lb_app.api`.

**Acceptance Criteria:**
- `lb_ui` contains no UI-agnostic viewmodel logic.
- `lb_ui` imports viewmodel helpers only from `lb_app.api`.
- Tests pass for run/dashboard viewmodels and TUI adapters.

## Notes
- 2026-01-23: Issue created.
- 2026-01-23: Moved run viewmodels to `lb_app/viewmodels/run_viewmodels.py`.
- 2026-01-23: Moved dashboard viewmodel logic to `lb_app/viewmodels/dashboard.py` and added `lb_app.viewmodels` exports.
- 2026-01-23: Updated `lb_app.api` exports and rewired `lb_ui` to use the API-only viewmodels.
- 2026-01-23: Kept `event_status_line` as a TUI wrapper to apply theme styling.

## Testing
- 2026-01-23: `uv run pytest tests/unit/lb_ui/test_run_viewmodels.py tests/unit/lb_ui/test_dashboard_viewmodel.py tests/unit/lb_ui/test_adapters_dashboard.py`
