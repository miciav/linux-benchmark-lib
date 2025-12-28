## Description
Consolidate presenter and dashboard implementations with shared adapters to reduce duplication.

## Plan
1. Introduce `PresenterBase` with a configurable sink for headless vs rich output.
2. Create `DashboardAdapter` supporting headless and threaded variants.
3. Update `HeadlessPresenter`, `RichPresenter`, and dashboard handles to delegate.
4. Add UI unit tests for headless and threaded modes.

## Acceptance Criteria
- Presenter/dashboard duplication is removed.
- Unit UI tests remain green.

## Risk
Medium.

## Evidence
- `arch_report/duplication_candidates_lb_ui.txt`
- `lb_ui/tui/system/headless.py:99`
- `lb_ui/tui/adapters/tui_adapter.py:80`
