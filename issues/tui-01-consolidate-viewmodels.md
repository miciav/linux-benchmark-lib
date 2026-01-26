# Issue: Consolidate TUI ViewModel Logic

**Title:** Refactor: Consolidate journal/plan viewmodels into a single source of truth

**Priority:** Medium
**Component:** lb_ui

**Description:**
Viewmodel logic is duplicated across `lb_ui/presenters/journal.py`, `lb_ui/presenters/viewmodels.py`, and `lb_ui/tui/system/components/dashboard_helpers.py`. This causes drift risk and makes UI behavior inconsistent (e.g., progress/status mapping). We should centralize the run/journal/plan transformation logic in one presenter module and make all UI renderers consume it.

**Detailed Plan:**
1. Define a canonical module (e.g., `lb_ui/presenters/run_viewmodels.py`) that exposes:
   - `target_repetitions(journal)`
   - `summarize_progress(tasks, target_reps)`
   - `journal_rows(journal)`
   - `plan_rows(plan)`
2. Update `lb_ui/presenters/journal.py` to call the canonical functions instead of duplicating logic.
3. Update `lb_ui/tui/system/components/dashboard_helpers.py` to call the canonical functions and remove duplicated status/progress code there.
4. Update any other callers (CLI presenters, dashboard) to import from the canonical module only.
5. Keep public APIs (`build_journal_table`, `build_run_plan_table`) stable; they should delegate to the canonical module.
6. Add/update tests to ensure the consolidated functions produce identical output to current behavior.

**Acceptance Criteria:**
- There is a single module that owns run/journal/plan transformation logic.
- No duplicate implementations of `summarize_progress` or `target_repetitions` remain.
- All UI paths render consistent status/progress values.
- Tests cover at least the journal summary and progress status mapping.

## Notes
- 2026-01-23: Added `lb_ui/presenters/run_viewmodels.py` as the canonical source and routed journal/plan/dashboard helpers to it.
- 2026-01-23: Removed duplicated viewmodel logic and deleted `lb_ui/presenters/viewmodels.py`.
- 2026-01-23: Added unit coverage for progress status mapping and metadata repetition precedence.

## Testing
- 2026-01-23: `uv run pytest tests/unit/lb_ui/test_cli_run_summary.py tests/unit/lb_ui/test_run_viewmodels.py`
